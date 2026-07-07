"""Contract tests for SentimentScorer's Chinese-language handling.

VADER ships no Chinese lexicon, so the scorer's treatment of Chinese commit
messages is governed entirely by the lexicon_patch entries and the CJK/Latin
ratio blend in analyzer.SentimentScorer.score. Nothing else in the suite pins
that contract, so a future lexicon or blend-formula edit could silently move the
emotional baseline for every Chinese-speaking user without breaking a test.

These tests fix, as the code behaves today:

  * a pure-Chinese message with no lexicon-patch term scores *exactly* 0.0 --
    VADER is blind to Chinese, so neither cheerful nor stressful semantic
    content leaks into the score without an explicit patch entry (this is a
    known limitation the score deliberately lives with, not a bug to "fix");
  * the CJK/Latin ratio blend of a real zh entry against the English VADER
    component, pinned to the arithmetic it produces;
  * a pure-Chinese patch hit still yields the expected positive polarity.

The routine-engineering-vocab neutralization (fix/bug/crash -> 0.0) is already
covered in test_scoring_fairness.py and is intentionally not repeated here.
"""

from __future__ import annotations

import pytest

from commit_shrink.analyzer import SentimentScorer
from commit_shrink.diagnoser import Diagnoser
from commit_shrink.pipeline import load_config


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def scorer(cfg) -> SentimentScorer:
    # Same construction the pipeline uses: the lexicon patch plus the
    # alexithymia stoplist (the ALL-CAPS scream gate consults it).
    diag = Diagnoser(cfg)
    return SentimentScorer(cfg["lexicon_patch"], stoplist=diag.stoplist)


class TestPureChineseIsInvisibleToVader:
    """A pure-Chinese message that trips no lexicon-patch entry scores exactly
    0.0 regardless of its human sentiment: VADER sees no tokens it recognizes,
    and there is no zh hit to blend in, so the score falls through to the
    (zero) raw VADER compound. Both polarities land on the same 0.0."""

    def test_positive_pure_chinese_no_patch_scores_zero(self, scorer):
        # Semantically upbeat ("3x faster, very satisfied") but no patch term.
        msg = "优化数据库查询性能，响应速度提升三倍，非常满意"
        assert scorer.raw_vader(msg) == 0.0
        assert scorer.score(msg) == 0.0

    def test_stressful_pure_chinese_no_patch_scores_zero(self, scorer):
        # Semantically alarming ("emergency prod-incident fix") but no patch
        # term -- note it avoids the '崩了'/'炸了' style entries on purpose.
        msg = "紧急修复生产环境事故"
        assert scorer.raw_vader(msg) == 0.0
        assert scorer.score(msg) == 0.0


class TestCjkEnglishBlend:
    """A message mixing a real zh lexicon hit with English text is scored by
    the CJK-ratio blend: ratio*zh_component + (1-ratio)*en_component."""

    def test_blend_is_cjk_ratio_weighted(self, scorer, cfg):
        # 完美 (a zh entry, +0.8) followed by English "clean solution", which
        # VADER scores positively on its own. 2 CJK chars, 13 Latin letters
        # -> ratio = 2/15; the two components are averaged by that ratio.
        msg = "完美 clean solution"
        score = scorer.score(msg)
        assert score == pytest.approx(0.6374133333333334)

        # Prove it is genuinely the ratio blend and not one component alone:
        # the English part carries real VADER weight and the zh entry pulls it
        # up, so the result sits strictly between them.
        ratio = 2 / 15
        zh = float(cfg["lexicon_patch"]["entries"]["完美"])  # 0.8
        en = scorer.raw_vader(msg)  # VADER of the Latin words (CJK ignored)
        assert en == pytest.approx(0.6124)
        assert score == pytest.approx(ratio * zh + (1 - ratio) * en)
        assert en < score < zh


class TestChineseLexiconPatch:
    """A pure-Chinese message that does hit patch entries still produces a
    meaningful signal -- the lexicon patch is what gives Chinese any polarity
    at all, so this pins that it still fires."""

    def test_pure_chinese_patch_hit_scores_positive(self, scorer, cfg):
        # 终于 (+0.6) and 搞定 (+0.7) both hit; mean 0.65 blended by the CJK
        # ratio (4 CJK chars vs 3 Latin "API") -> 4/7 * 0.65.
        msg = "终于搞定API"
        score = scorer.score(msg)
        assert score > 0.3
        assert score == pytest.approx(0.37142857142857133)

        ents = cfg["lexicon_patch"]["entries"]
        zh_mean = (float(ents["终于"]) + float(ents["搞定"])) / 2
        assert score == pytest.approx((4 / 7) * zh_mean)
