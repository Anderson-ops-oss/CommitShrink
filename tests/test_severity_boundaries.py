"""Direct-call severity-ladder tests for detectors whose thresholds the golden
demo fixture only lands on once (so a single golden assertion cannot pin the
whole I..IV ladder).

Each rung is exercised by calling the detector on a hand-built Commit list with
controlled timestamps, and the expected grade was confirmed by running the code
before it was hard-coded here (no guessed numbers). Ratio-type detectors
(_night_despair, _boundary) are fed a real PeriodStats from compute_stats, so
the sentiment and schedule aggregates match production exactly.

Cases deliberately avoided because they already live in test_scoring_fairness.py
/ test_new_symptoms.py: night_mood>=0 cap, weekend 6-vs-5 -> III and
overwhelming -> IV, the burden discount/cap/floor, is_low_info, routine-vocab
neutralization, and the ci_appeasement / empty_commit ladders.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from commit_shrink.analyzer import SentimentScorer, compute_stats
from commit_shrink.diagnoser import WEEKEND_IV_MIN, Diagnoser
from commit_shrink.models import Commit
from commit_shrink.pipeline import load_config

# A pure-Chinese distress message. VADER is blind to CJK, so its whole (negative)
# score comes from the lexicon patch; a list of identical copies therefore has a
# night_mood equal to this single, deterministic value.
NEG = "崩了 卧槽 又炸了"
NEG_SCORE = -0.5  # observed score of NEG under the patched lexicon


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def diag(cfg) -> Diagnoser:
    return Diagnoser(cfg)


@pytest.fixture(scope="module")
def scorer(cfg, diag) -> SentimentScorer:
    return SentimentScorer(cfg["lexicon_patch"], stoplist=diag.stoplist)


def _c(message: str, *, day: int = 0, hour: int = 12, minute: int | None = None,
       i: int = 0, files=("a.py",)) -> Commit:
    # Anchor on 2026-01-05 (a Monday); day 5 = Saturday, day 6 = Sunday.
    # is_night is 00:00-05:59 in local (UTC here) time.
    return Commit(
        sha=f"{i:040x}",
        author_name="D",
        author_email="d@d",
        ts=datetime(2026, 1, 5 + day, hour, i % 60 if minute is None else minute,
                    tzinfo=timezone.utc),
        message=message,
        file_paths=list(files),
    )


def _stats(commits, scorer, diag):
    scores = {c.sha: scorer.score(c.message) for c in commits}
    return compute_stats(commits, scores, diag.stoplist)


# ---- GIT-<night>: _night_despair ratio ladder (night_mood < 0) -------------


class TestNightDespairLadder:
    """With a negative night mood, severity climbs the night_ratio ladder:
    II >0.25, III >0.35, IV >0.50. (The mood>=0 cap is covered elsewhere.)"""

    def _night(self, n_night, n_day, diag, scorer):
        commits = [_c(NEG, hour=2, i=i) for i in range(n_night)] + [
            _c("feat daytime work", hour=14, i=i + n_night) for i in range(n_day)
        ]
        return commits, _stats(commits, scorer, diag)

    def test_ratio_30pct_grade_II(self, diag, scorer):
        commits, st = self._night(3, 7, diag, scorer)
        assert st.night_ratio == pytest.approx(0.30) and st.night_mood < 0
        d = diag._night_despair(commits, st)
        assert d is not None and d.id == "night_despair"
        assert d.severity == "II" and d.args["ratio"] == "30%"

    def test_ratio_40pct_grade_III(self, diag, scorer):
        commits, st = self._night(4, 6, diag, scorer)
        assert st.night_ratio == pytest.approx(0.40) and st.night_mood < 0
        d = diag._night_despair(commits, st)
        assert d is not None and d.severity == "III" and d.args["ratio"] == "40%"

    def test_ratio_60pct_grade_IV(self, diag, scorer):
        commits, st = self._night(6, 4, diag, scorer)
        assert st.night_ratio == pytest.approx(0.60) and st.night_mood < 0
        d = diag._night_despair(commits, st)
        assert d is not None and d.severity == "IV" and d.args["ratio"] == "60%"

    def test_mood_only_entry_path_grade_I(self, diag, scorer):
        # ratio <= 0.15 (below the by_ratio gate), so the detector fires only
        # via the by_mood path (night_count>0 AND night_mood < -0.3); with the
        # ratio so low the grade lands at I.
        commits, st = self._night(1, 9, diag, scorer)
        assert st.night_ratio == pytest.approx(0.10) and st.night_ratio <= 0.15
        assert st.night_mood < -0.3 and st.night_mood == NEG_SCORE
        d = diag._night_despair(commits, st)
        assert d is not None and d.severity == "I" and d.args["ratio"] == "10%"


# ---- GIT-<boundary>: _boundary rungs II/III with weekend_count < 5 ---------


class TestBoundaryLadder:
    """II >0.30, III >0.45 -- both below the WEEKEND_IV_MIN volume gate, so
    neither can reach IV no matter how the ratio is arranged."""

    def _weekend(self, n_weekend, n_weekday, diag, scorer):
        commits = [_c("work", day=5, hour=12, i=i) for i in range(n_weekend)] + [
            _c("work", day=0, hour=12, i=i + n_weekend) for i in range(n_weekday)
        ]
        return commits, _stats(commits, scorer, diag)

    def test_ratio_40pct_grade_II(self, diag, scorer):
        commits, st = self._weekend(4, 6, diag, scorer)
        assert st.weekend_ratio == pytest.approx(0.40) and st.weekend_count == 4
        d = diag._boundary(commits, st)
        assert d is not None and d.id == "boundary_dissolution"
        assert d.severity == "II" and d.args["ratio"] == "40%"

    def test_ratio_50pct_below_volume_gate_grade_III(self, diag, scorer):
        commits, st = self._weekend(4, 4, diag, scorer)
        assert st.weekend_ratio == pytest.approx(0.50)
        assert st.weekend_count == 4 and st.weekend_count < WEEKEND_IV_MIN
        d = diag._boundary(commits, st)
        assert d is not None and d.severity == "III" and d.args["ratio"] == "50%"


# ---- GIT-31.0: _decision_regret ladder ------------------------------------


class TestDecisionRegretLadder:
    def _reverts(self, n_rev, n_plain, *, recursive=False):
        if recursive:
            revs = [_c('Revert "Revert "feature Y""', i=0)] + [
                _c('Revert "feature X"', i=k) for k in range(1, n_rev)
            ]
        else:
            revs = [_c('Revert "feature X"', i=k) for k in range(n_rev)]
        plains = [_c("add feature", i=1000 + k) for k in range(n_plain)]
        return revs + plains

    def test_single_revert_grade_I(self, diag):
        # 1 revert out of 10 -> ratio 0.10 (NOT > 0.10), n < 2 -> I.
        d = diag._decision_regret(self._reverts(1, 9))
        assert d is not None and d.id == "decision_regret" and d.code == "GIT-31.0"
        assert d.severity == "I" and d.args["n"] == 1

    def test_two_reverts_grade_II(self, diag):
        # 2 reverts out of 20 -> ratio 0.10 (not > 0.10), n >= 2 -> II.
        d = diag._decision_regret(self._reverts(2, 18))
        assert d is not None and d.severity == "II" and d.args["n"] == 2

    def test_four_reverts_grade_III_by_count(self, diag):
        # n >= 4 forces III even with a tiny ratio (4 / 44 ~= 0.09).
        d = diag._decision_regret(self._reverts(4, 40))
        assert d is not None and d.severity == "III" and d.args["n"] == 4

    def test_high_ratio_grade_III_by_ratio(self, diag):
        # n == 3 (< 4) but ratio 3/13 ~= 0.23 > 0.10 -> III.
        d = diag._decision_regret(self._reverts(3, 10))
        assert d is not None and d.severity == "III" and d.args["n"] == 3

    def test_recursive_revert_grade_IV(self, diag):
        d = diag._decision_regret(self._reverts(2, 5, recursive=True))
        assert d is not None and d.severity == "IV"
        assert d.notes["recursive_note"]["show"] is True


# ---- GIT-<anxious>: _anxious episode count ---------------------------------


class TestAnxiousCommittingLadder:
    def _burst(self, hour, count, i0):
        # `count` commits one minute apart within a single hour.
        return [_c("wip", hour=hour, minute=m, i=i0 + m) for m in range(count)]

    def test_single_burst_is_one_episode_returns_none(self, diag):
        # One tight burst of 5 = a single episode; the detector needs >= 2
        # distinct episodes to fire, so this yields None.
        commits = self._burst(0, 5, 0)
        assert diag._anxious(commits) is None

    def test_three_bursts_grade_II(self, diag):
        # Three bursts of 5, two hours apart (>> the 30-min window) so they do
        # not merge -> 3 episodes, peak 5 (< 10) -> II.
        commits = (
            self._burst(0, 5, 0) + self._burst(2, 5, 100) + self._burst(4, 5, 200)
        )
        d = diag._anxious(commits)
        assert d is not None and d.id == "anxious_committing"
        assert d.severity == "II" and d.args["n"] == 3 and d.args["peak"] == 5
