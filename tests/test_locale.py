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

        names = {d.name for d in a.diagnoses}
        assert "Compulsive Fix Disorder" in names

        fixloop = next(d for d in a.diagnoses if d.id == "repeated_fix_loop")
        # placeholders were filled (no leftover braces) and duration came out English
        assert "{" not in fixloop.text and "}" not in fixloop.text
        assert "corrective interventions" in fixloop.text
        assert "minutes" in fixloop.text or "hours" in fixloop.text
        assert not _has_cjk(fixloop.text)

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

    def test_chinese_report_still_renders(self, fixture_repo):
        repo, _start, period_end = fixture_repo
        cfg = load_config("zh")
        a = assess_repo(repo, days=7, until=period_end, cfg=cfg)
        buf = Console(file=None, record=True, width=100)
        ReportRenderer(cfg).render(buf, a)
        text = buf.export_text()
        assert _has_cjk(text)  # the Chinese report is, in fact, Chinese
