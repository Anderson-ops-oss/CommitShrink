"""Tests for the display-copy locale overlay (commit_shrink/data/locales).

The locale mechanism must (1) leave detection rules untouched, (2) replace
every display string, including the separators report.py used to hardcode,
and (3) never leave a Chinese character or an unfilled {placeholder} in an
English report.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from commit_shrink.pipeline import SUPPORTED_LANGS, assess_repo, load_config
from commit_shrink.report import ReportRenderer


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


class TestLoadConfigLocale:
    def test_default_is_chinese_base(self):
        cfg = load_config()
        syms = {s["id"]: s for s in cfg["symptoms"]}
        assert syms["repeated_fix_loop"]["name"] == "强迫性修复障碍"
        assert cfg["report_copy"]["label_sep"] == "　"  # ideographic space

    def test_english_overlay_replaces_display_copy(self):
        cfg = load_config("en")
        syms = {s["id"]: s for s in cfg["symptoms"]}
        assert syms["repeated_fix_loop"]["name"] == "Compulsive Fix Disorder"
        assert cfg["report_copy"]["header_labels"]["patient"] == "Subject"
        assert cfg["meta"]["severity_labels"]["IV"].startswith("Extreme")
        # ASCII separators replace the fullwidth ones
        assert cfg["report_copy"]["label_sep"] == ": "
        assert cfg["report_copy"]["diagnosis_labels"]["secondary_join"] == " | "

    def test_detection_rules_survive_the_overlay(self):
        """A locale supplies display copy only; triggers/severity/norms stay."""
        cfg = load_config("en")
        fix = next(s for s in cfg["symptoms"] if s["id"] == "repeated_fix_loop")
        assert fix["code"] == "GIT-42.2"
        assert "trigger" in fix and "pattern" in fix["trigger"]
        assert set(fix["severity"]) == {"I", "II", "III", "IV"}
        # metric norm parameters are untouched by the name overlay
        night = next(m for m in cfg["metrics"] if m["id"] == "night_despair_index")
        assert night["name"] == "Nocturnal Despair Index"
        assert night["norm"]["mean"] == 3.5

    def test_all_15_symptoms_have_english_display_fields(self):
        cfg = load_config("en")
        assert len(cfg["symptoms"]) == 15
        for s in cfg["symptoms"]:
            for field in ("name", "diagnosis", "prescription"):
                assert s[field], f"{s['id']} missing {field}"
                assert not _has_cjk(s[field]), f"{s['id']}.{field} still has CJK"

    def test_loading_messages_present_in_both_languages(self):
        """The waiting-room lines are locale copy like everything else: a
        non-empty list in each language, natively worded (not translated), and
        the en overlay wholesale-replaces the zh list (equal length by design).
        """
        zh = load_config("zh")["report_copy"]["loading_messages"]
        en = load_config("en")["report_copy"]["loading_messages"]
        assert zh and en and len(zh) == len(en)
        assert all(isinstance(m, str) and m.strip() for m in zh + en)
        assert all(not _has_cjk(m) for m in en)  # English lines are English
        assert any(_has_cjk(m) for m in zh)  # Chinese lines are Chinese

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError):
            load_config("fr")

    def test_supported_langs_contract(self):
        assert SUPPORTED_LANGS == ("zh", "en")


class TestEnglishAssessmentRenders:
    def test_english_diagnoses_are_formatted_english(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        cfg = load_config("en")
        a = assess_repo(repo, days=7, until=period_end, cfg=cfg)
        renderer = ReportRenderer(cfg)

        names = {renderer.diagnosis_name(d) for d in a.diagnoses}
        assert "Compulsive Fix Disorder" in names

        fixloop = next(d for d in a.diagnoses if d.id == "repeated_fix_loop")
        text = renderer.diagnosis_text(fixloop)
        # placeholders were filled (no leftover braces) and duration came out English
        assert "{" not in text and "}" not in text
        assert "corrective interventions" in text
        assert "minutes" in text or "hours" in text
        assert not _has_cjk(text)

    def test_full_english_report_has_no_cjk(self, fixture_repo):
        """Render the whole report to a string buffer and assert it is CJK-free
        end to end — this is the check that would have caught the hardcoded
        U+3000 / fullwidth separators leaking out of report.py.
        """
        repo, _start, period_end = fixture_repo
        cfg = load_config("en")
        a = assess_repo(repo, days=7, until=period_end, cfg=cfg)

        buf = Console(file=None, record=True, width=100)
        ReportRenderer(cfg).render(buf, a)
        text = buf.export_text()
        cjk = sorted({ch for ch in text if _has_cjk(ch)})
        assert not cjk, f"English report leaked CJK characters: {cjk}"

    def test_english_spacing_and_fold_artifacts(self, fixture_repo):
        """Guards against the glued-separator and YAML-fold artifacts that only
        surfaced when the report was actually rendered (not caught by key/
        placeholder checks): a severity paren must not glue to the diagnosis
        name, the report-date suffix must not glue to the timestamp, and a
        hyphenated compound must not gain a fold space.
        """
        repo, _start, period_end = fixture_repo
        cfg = load_config("en")
        a = assess_repo(repo, days=7, until=period_end, cfg=cfg)
        buf = Console(file=None, record=True, width=100)
        ReportRenderer(cfg).render(buf, a)
        text = buf.export_text()

        assert "Disorder (Extreme)" in text and "Disorder(Extreme" not in text
        assert "Extreme (Clinically Significant))" not in text  # no nested parens
        assert "quantitative-assessment genre" in text
        assert "quantitative- assessment" not in text  # >- fold must not split the hyphen

    def test_english_trend_note_spaces_the_extrapolation_sentence(self):
        """The decline-streak sentence and the extrapolation sentence are two
        appended clauses; in English they must not glue (".Extrapolating").
        The separating space lives in the en locale (zh needs none). Rendered
        without a Trend, the report omits this line, so it is checked directly.
        """
        from types import SimpleNamespace

        renderer = ReportRenderer(load_config("en"))
        trend = SimpleNamespace(composite_delta=-2, decline_streak=2, extrapolated_week=30)
        note = renderer._trend_note(trend)
        assert "decline. Extrapolating" in note
        assert "decline.Extrapolating" not in note

    def test_chinese_report_still_renders(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        cfg = load_config("zh")
        a = assess_repo(repo, days=7, until=period_end, cfg=cfg)
        buf = Console(file=None, record=True, width=100)
        ReportRenderer(cfg).render(buf, a)
        text = buf.export_text()
        assert _has_cjk(text)  # the Chinese report is, in fact, Chinese


class TestDeferredRendering:
    """The mechanism the Streamlit language switch relies on: assess once, then
    render the SAME Assessment in either language with no re-assessment."""

    def _render(self, cfg, a) -> str:
        buf = Console(file=None, record=True, width=100)
        ReportRenderer(cfg).render(buf, a)
        return buf.export_text()

    def test_one_assessment_renders_both_languages(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        # Assess ONCE. The result is language-neutral.
        a = assess_repo(repo, days=7, until=period_end, cfg=load_config("zh"))

        zh = self._render(load_config("zh"), a)
        en = self._render(load_config("en"), a)

        assert _has_cjk(zh) and "强迫性修复障碍" in zh
        assert not any(_has_cjk(ch) for ch in en) and "Compulsive Fix Disorder" in en

    def test_assessment_is_language_neutral(self, fixture_repo):
        """Assessing with the zh vs en config yields identical detection output
        (ids, severities, and the neutral template args) -- proof that no
        display language is baked into the Assessment."""
        repo, _start, period_end = fixture_repo
        a_zh = assess_repo(repo, days=7, until=period_end, cfg=load_config("zh"))
        a_en = assess_repo(repo, days=7, until=period_end, cfg=load_config("en"))

        assert [(d.id, d.severity) for d in a_zh.diagnoses] == [
            (d.id, d.severity) for d in a_en.diagnoses
        ]
        for dz, de in zip(a_zh.diagnoses, a_en.diagnoses):
            assert dz.args == de.args
            assert dz.notes == de.notes
        assert a_zh.notes == a_en.notes
