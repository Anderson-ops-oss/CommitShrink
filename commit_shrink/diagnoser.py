"""Rule engine: evaluates the symptom table against a commit history.

Every joke lives in commit_shrink/data/symptoms.yaml; this module is the
executable interpretation of its trigger/severity prose. Structure:

- pass 1: independent detectors, one per symptom id;
- pass 2: cross-reference grades per meta.ranking (GIT-13.0 IV needs a
  confirmed GIT-42.2 chain; GIT-70.7 IV is graded on a single commit that
  also satisfies the GIT-99.0 trigger);
- grading: candidates (chains / segments / episodes) are graded individually
  and the highest grade wins, per meta.grading_rule;
- ranking: (severity, evidence size) descending -> primary / secondary / other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .analyzer import (
    PeriodStats,
    is_low_info,
    is_scream,
    normalize_message,
    techdebt_hash,
)
from .models import Commit

SEVERITY_ORDER = {"I": 1, "II": 2, "III": 3, "IV": 4}
SEGMENT_GAP = timedelta(hours=2)
NIGHT_CHAIN_MIN = 5
WEEKEND_IV_MIN = 5  # minimum weekend commits before boundary_dissolution can reach IV
_RECURSIVE_REVERT_RE = re.compile(r'Revert\s+"Revert', re.IGNORECASE)
_VERSION_3PLUS_RE = re.compile(r"\bv(?:[3-9]|[1-9]\d+)\b", re.IGNORECASE)


@dataclass
class Diagnosis:
    """A detection result, free of display strings.

    The diagnosis prose, name, and prescription are rendered from the config
    at display time (report.ReportRenderer), so the same result can be shown
    in any language. `args` holds the language-neutral values a diagnosis
    template needs (ints, pre-formatted %/±numbers, strftime times, the masked
    evidence subject; a duration is carried raw as `duration_td` because its
    unit words are language-specific). `notes` drives the optional
    diagnosis_notes clauses: {note_key: {"show": bool, "args": {...}}}.
    """

    id: str
    code: str
    severity: str  # I..IV
    evidence: list[Commit] = field(default_factory=list)
    masked: bool = False  # evidence quoted in the diagnosis text was redacted
    args: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    template_key: str = "diagnosis"  # "diagnosis_alt" selects a branch template

    @property
    def rank_key(self) -> tuple[int, int]:
        return (SEVERITY_ORDER[self.severity], len(self.evidence))


def _fmt_time(commit: Commit) -> str:
    return commit.ts.strftime("%m-%d %H:%M")


def _topic_paths(commit: Commit) -> set[str]:
    paths = set(commit.file_paths)
    for old_path, new_path in commit.renames:
        paths.add(old_path)
        paths.add(new_path)
    return paths


class Diagnoser:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.spec = {s["id"]: s for s in cfg["symptoms"]}
        flags = re.IGNORECASE

        def pat(sid: str, key: str = "pattern") -> re.Pattern:
            return re.compile(self.spec[sid]["trigger"][key], flags)

        self.re_fix = pat("repeated_fix_loop")
        self.re_final = pat("naming_collapse")
        self.re_revert = pat("decision_regret")
        self.re_emo = pat("emotional_outburst")
        self.re_p0 = pat("p0_incident")
        self.re_wip = pat("commitment_avoidance")
        self.re_magic = pat("magical_thinking")
        self.re_debt = pat("stockholm_techdebt")
        self.re_quick = pat("time_perception")
        self.re_ci = pat("ci_appeasement")
        self.stoplist = self.spec["alexithymia"]["trigger"]["stoplist"]

        # Filled during run(); used by cross-reference upgrades and the report.
        self._fix_chain_shas: set[str] = set()

    # -- shared helpers -----------------------------------------------------

    def mask(self, text: str) -> tuple[str, bool]:
        """Redact outburst-lexicon hits: keep the first char, x-out the rest."""

        def repl(m: re.Match) -> str:
            token = m.group(0)
            informative = sum(
                1 for ch in token if ch.isalnum() or "一" <= ch <= "鿿"
            )
            if informative < 2:
                return token  # pure punctuation bursts stay visible
            return token[0] + "×" * (len(token) - 1)

        masked = self.re_emo.sub(repl, text)
        return masked, masked != text

    def _segments(self, commits: list[Commit]) -> list[list[Commit]]:
        """Split into topic segments: same repo AND gap < 2h AND overlapping
        file sets. The same-repo guard matters only for a merged multi-repo
        (gh-user) timeline -- it stops identically-named files in different
        repos (README.md, __init__.py) from being read as one topic; in a
        single-repo assessment every commit shares the empty repo_key."""
        segments: list[list[Commit]] = []
        current: list[Commit] = []
        for c in commits:
            if c.is_merge:
                continue
            if current:
                prev = current[-1]
                gap_ok = (c.ts - prev.ts) < SEGMENT_GAP  # yaml: "相邻间隔 <2h"
                same_repo = prev.repo_key == c.repo_key
                overlap = bool(_topic_paths(prev) & _topic_paths(c))
                if gap_ok and same_repo and overlap:
                    current.append(c)
                    continue
                segments.append(current)
            current = [c]
        if current:
            segments.append(current)
        return segments

    def _diag(
        self,
        sid: str,
        severity: str,
        evidence: list[Commit],
        *,
        args: dict | None = None,
        notes: dict | None = None,
        template_key: str = "diagnosis",
        masked: bool = False,
    ) -> Diagnosis:
        return Diagnosis(
            id=sid,
            code=self.spec[sid]["code"],
            severity=severity,
            evidence=evidence,
            masked=masked,
            args=args or {},
            notes=notes or {},
            template_key=template_key,
        )

    # -- detectors ----------------------------------------------------------

    def _grade_chain(self, chain: list[Commit]) -> str:
        n = len(chain)
        all_caps = any(is_scream(c.message, self.stoplist) for c in chain)
        if n >= NIGHT_CHAIN_MIN and all(c.is_night for c in chain):
            return "IV"
        if n >= NIGHT_CHAIN_MIN or all_caps:
            return "III"
        return "II" if n == 4 else "I"

    def _fix_loop(self, segments: list[list[Commit]]) -> Diagnosis | None:
        chains = [s for s in segments if sum(1 for c in s if self.re_fix.search(c.message)) >= 3]
        self._fix_chain_shas = {c.sha for s in chains for c in s}
        if not chains:
            return None
        # Grade every chain and let the highest grade win (meta.grading_rule).
        sev, worst = max(
            ((self._grade_chain(c), c) for c in chains),
            key=lambda g: (SEVERITY_ORDER[g[0]], len(g[1])),
        )
        return self._diag(
            "repeated_fix_loop",
            sev,
            worst,
            args={"n": len(worst), "duration_td": worst[-1].ts - worst[0].ts},
        )

    @staticmethod
    def _grade_naming(hits: list[Commit], variants: list[str]) -> str:
        if any(_VERSION_3PLUS_RE.search(c.message) for c in hits):
            return "IV"
        if len(variants) >= 5 or any("FINAL" in c.message for c in hits):
            return "III"
        return "II" if len(variants) >= 3 else "I"

    def _naming_collapse(self, segments: list[list[Commit]]) -> Diagnosis | None:
        candidates: list[tuple[str, list[Commit], list[str]]] = []
        for seg in segments:
            hits = [c for c in seg if self.re_final.search(c.message)]
            variants = list(dict.fromkeys(normalize_message(c.message) for c in hits))
            if len(variants) >= 2:
                candidates.append((self._grade_naming(hits, variants), hits, variants))
        if not candidates:
            return None
        # Grade every segment; the highest grade wins (meta.grading_rule).
        sev, hits, variants = max(
            candidates, key=lambda c: (SEVERITY_ORDER[c[0]], len(c[2]))
        )
        return self._diag("naming_collapse", sev, hits, args={"n": len(variants)})

    def _decision_regret(self, period: list[Commit]) -> Diagnosis | None:
        reverts = [c for c in period if self.re_revert.search(c.message)]
        if not reverts:
            return None
        n = len(reverts)
        ratio = n / len(period)
        recursive = any(_RECURSIVE_REVERT_RE.search(c.message) for c in reverts)
        if recursive:
            sev = "IV"
        elif n >= 4 or ratio > 0.10:
            sev = "III"
        elif n >= 2:
            sev = "II"
        else:
            sev = "I"
        return self._diag(
            "decision_regret",
            sev,
            reverts,
            args={"n": n},
            notes={"recursive_note": {"show": recursive}},
        )

    def _emotional_outburst(self, period: list[Commit], scores: dict[str, float]) -> Diagnosis | None:
        hits = [c for c in period if self.re_emo.search(c.message)]
        if not hits:
            return None
        n = len(hits)
        peak = min(hits, key=lambda c: scores[c.sha])
        if n >= 10 or scores[peak.sha] < -0.9:
            sev = "IV"
        elif n >= 6:
            sev = "III"
        elif n >= 3:
            sev = "II"
        else:
            sev = "I"
        evidence_text, masked = self.mask(peak.subject)
        return self._diag(
            "emotional_outburst",
            sev,
            hits,
            args={"n": n, "time": _fmt_time(peak), "evidence": evidence_text},
            masked=masked,
        )

    def _p0_incident(self, period: list[Commit]) -> Diagnosis | None:
        events = [c for c in period if c.is_night and self.re_p0.search(c.message)]
        if not events:
            return None
        first = events[0]
        evidence_text, masked = self.mask(first.subject)
        return self._diag(
            "p0_incident",
            "IV",
            events,
            args={"time": _fmt_time(first), "evidence": evidence_text},
            masked=masked,
        )

    def _night_despair(self, period: list[Commit], stats: PeriodStats) -> Diagnosis | None:
        by_ratio = stats.night_ratio > 0.15
        by_mood = stats.night_count > 0 and stats.night_mood < -0.3
        if not (by_ratio or by_mood):
            return None
        # Escalation past grade I requires the night mood to actually be down: a
        # night owl whose small-hours commits read neutral or cheerful is a
        # chronotype, not distress. Schedule alone (non-negative night_mood) caps
        # at I. This also keeps the mood-only entry path (ratio <=15%) at I.
        if stats.night_mood >= 0:
            sev = "I"
        elif stats.night_ratio > 0.50:
            sev = "IV"
        elif stats.night_ratio > 0.35:
            sev = "III"
        elif stats.night_ratio > 0.25:
            sev = "II"
        else:
            sev = "I"
        # The "below daytime baseline" claim needs actual daytime samples.
        has_day_samples = stats.total > stats.night_count
        show_mood = bool(
            stats.night_count and has_day_samples and stats.night_mood < stats.day_mood
        )
        return self._diag(
            "night_despair",
            sev,
            [c for c in period if c.is_night],
            args={"ratio": f"{stats.night_ratio * 100:.0f}%"},
            notes={
                "night_mood_note": {
                    "show": show_mood,
                    "args": {"night_mood": f"{stats.night_mood:+.2f}"},
                }
            },
        )

    def _boundary(self, period: list[Commit], stats: PeriodStats) -> Diagnosis | None:
        if stats.weekend_ratio <= 0.20 and stats.weekend_count <= stats.weekday_count:
            return None
        # IV needs a genuinely extreme, non-trivial weekend share. A bare
        # weekend_count > weekday_count graded a 6-vs-5 weekend-leaning hobby repo
        # "most severe" -- which reads as a bug, not a joke, since weekend work on
        # a side project is the boundary *working*. Require a strong majority AND
        # enough volume for the top grade.
        if stats.weekend_ratio > 0.60 and stats.weekend_count >= WEEKEND_IV_MIN:
            sev = "IV"
        elif stats.weekend_ratio > 0.45:
            sev = "III"
        elif stats.weekend_ratio > 0.30:
            sev = "II"
        else:
            sev = "I"
        return self._diag(
            "boundary_dissolution",
            sev,
            [c for c in period if c.is_weekend],
            args={"ratio": f"{stats.weekend_ratio * 100:.0f}%"},
        )

    def _anxious(self, period: list[Commit]) -> Diagnosis | None:
        commits = sorted(period, key=lambda c: c.ts)
        window = timedelta(minutes=30)
        spans: list[tuple[int, int, int]] = []  # (start_idx, end_idx, count)
        for i in range(len(commits)):
            j = i
            while j + 1 < len(commits) and commits[j + 1].ts - commits[i].ts < window:
                j += 1
            count = j - i + 1
            if count >= 5:
                spans.append((i, j, count))
        if not spans:
            return None
        # Greedy-merge overlapping windows into episodes.
        episodes: list[tuple[int, int, int]] = []
        for start, end, count in spans:
            if episodes and start <= episodes[-1][1]:
                prev = episodes[-1]
                episodes[-1] = (prev[0], max(prev[1], end), max(prev[2], count))
            else:
                episodes.append((start, end, count))
        if len(episodes) < 2:
            return None
        n = len(episodes)
        peak = max(e[2] for e in episodes)
        if peak >= 10:
            sev = "IV"
        elif n >= 5:
            sev = "III"
        elif n >= 3:
            sev = "II"
        else:
            sev = "I"
        biggest = max(episodes, key=lambda e: e[2])
        evidence = commits[biggest[0] : biggest[1] + 1]
        return self._diag("anxious_committing", sev, evidence, args={"n": n, "peak": peak})

    def _history(self, rewrites: int | None, notes: list[str]) -> Diagnosis | None:
        if rewrites is None:
            # Reflog unavailable: degrade to the "specimen declined" note, whose
            # display string is assembled from the config at render time.
            notes.append("history_revisionism")
            return None
        if rewrites == 0:
            return None
        if rewrites >= 10:
            sev = "IV"
        elif rewrites >= 6:
            sev = "III"
        elif rewrites >= 3:
            sev = "II"
        else:
            sev = "I"
        return self._diag("history_revisionism", sev, [], args={"n": rewrites})

    def _alexithymia(self, period: list[Commit], stats: PeriodStats) -> Diagnosis | None:
        ratio = stats.low_info_ratio
        if ratio <= 0.15:
            return None
        if ratio > 0.60:
            sev = "IV"
        elif ratio > 0.40:
            sev = "III"
        elif ratio > 0.25:
            sev = "II"
        else:
            sev = "I"
        evidence = [c for c in period if is_low_info(c.message, self.stoplist)]
        return self._diag("alexithymia", sev, evidence, args={"ratio": f"{ratio * 100:.0f}%"})

    def _binge(self, period: list[Commit], window: list[Commit]) -> Diagnosis | None:
        episodes: list[tuple[Commit, timedelta | None]] = []
        for c in period:
            if c.is_merge or (c.files_changed < 20 and c.insertions < 1000):
                continue
            # Prior activity is any of the patient's earlier non-merge commits.
            # (No author_email match: a single-repo run is already narrowed to
            # one email, and the merged gh-user timeline keeps the person's
            # several identities -- filtering by one email there would invent
            # "silence" before a commit landed under a secondary identity.)
            prior = [w for w in window if w.ts < c.ts and not w.is_merge]
            gap = (c.ts - prior[-1].ts) if prior else None
            if gap is None or gap >= timedelta(hours=72):
                episodes.append((c, gap))
        if not episodes:
            return None

        def level(c: Commit) -> str:
            # Any qualifying episode described as "update" is grade IV outright.
            if normalize_message(c.message) == "update":
                return "IV"
            if c.files_changed >= 80 or c.insertions >= 3000:
                return "III"
            if c.files_changed >= 40 or c.insertions >= 2000:
                return "II"
            return "I"

        # Grade every episode; the highest grade wins (meta.grading_rule).
        worst, gap = max(
            episodes, key=lambda e: (SEVERITY_ORDER[level(e[0])], e[0].files_changed)
        )
        sev = level(worst)
        return self._diag(
            "binge_committing",
            sev,
            [e[0] for e in episodes],
            args={"n": worst.files_changed, "duration_td": gap},
        )

    def _commitment(self, period: list[Commit], stats: PeriodStats) -> Diagnosis | None:
        hits = [c for c in period if self.re_wip.search(c.message)]
        ratio = len(hits) / stats.total if stats.total else 0.0
        longest_run = run = 0
        for c in period:
            run = run + 1 if self.re_wip.search(c.message) else 0
            longest_run = max(longest_run, run)
        if ratio <= 0.15 and longest_run < 3:
            return None
        if longest_run >= 5:
            sev = "IV"
        elif ratio > 0.40:
            sev = "III"
        elif ratio > 0.25 or longest_run == 4:
            sev = "II"
        else:
            sev = "I"
        return self._diag(
            "commitment_avoidance", sev, hits, args={"ratio": f"{ratio * 100:.0f}%"}
        )

    def _magical(self, period: list[Commit], scores: dict[str, float]) -> Diagnosis | None:
        hits = [c for c in period if self.re_magic.search(c.message)]
        if not hits:
            return None
        n = len(hits)
        with_p0 = any(c.is_night and self.re_p0.search(c.message) for c in hits)
        if with_p0:
            sev = "IV"
        elif n >= 4:
            sev = "III"
        elif n >= 2:
            sev = "II"
        else:
            sev = "I"
        rep = min(hits, key=lambda c: scores[c.sha])
        evidence_text, masked = self.mask(rep.subject)
        return self._diag(
            "magical_thinking",
            sev,
            hits,
            args={"n": n, "evidence": evidence_text},
            masked=masked,
        )

    def _techdebt_recurrence(
        self, hits: list[Commit], techdebt_history: dict[str, str] | None
    ) -> Commit | None:
        """A hit whose normalized message first appeared >=90 days ago,
        per the cross-period cache (history.py). None when there's no cache
        yet or no hit qualifies -- severity then caps at III, as before the
        cache existed.
        """
        if not techdebt_history:
            return None
        for c in hits:
            first_seen = techdebt_history.get(techdebt_hash(normalize_message(c.message)))
            if first_seen and c.ts - datetime.fromisoformat(first_seen) >= timedelta(days=90):
                return c
        return None

    def _stockholm(
        self, period: list[Commit], techdebt_history: dict[str, str] | None
    ) -> Diagnosis | None:
        hits = [c for c in period if self.re_debt.search(c.message)]
        if not hits:
            return None
        n = len(hits)
        recurring = self._techdebt_recurrence(hits, techdebt_history)
        if recurring is not None:
            sev = "IV"
        elif n >= 6:
            sev = "III"
        elif n >= 3:
            sev = "II"
        else:
            sev = "I"
        return self._diag(
            "stockholm_techdebt",
            sev,
            hits,
            args={"n": n},
            notes={"recurrence_note": {"show": recurring is not None}},
        )

    def _time_perception(self, period: list[Commit], window: list[Commit]) -> Diagnosis | None:
        confirmed: list[tuple[Commit, str, int]] = []  # (commit, branch, n_or_lines)
        for c in period:
            if not self.re_quick.search(c.message):
                continue
            lines = c.insertions + c.deletions
            if lines > 300:
                confirmed.append((c, "diff", lines))
                continue
            follows = [
                w
                for w in window
                if c.ts < w.ts <= c.ts + timedelta(hours=24)
                and w.sha != c.sha
                and w.repo_key == c.repo_key  # a fix in another repo isn't a follow-up
                and self.re_fix.search(w.message)
            ]
            if len(follows) >= 2:
                confirmed.append((c, "follow", len(follows)))
        if not confirmed:
            return None
        n = len(confirmed)
        in_chain = any(c.sha in self._fix_chain_shas for c, _, _ in confirmed)
        if in_chain:
            sev = "IV"
        elif n >= 4:
            sev = "III"
        elif n >= 2:
            sev = "II"
        else:
            sev = "I"
        first, branch, value = confirmed[0]
        evidence_text, masked = self.mask(first.subject)
        evidence = [c for c, _, _ in confirmed]
        if branch == "diff":
            return self._diag(
                "time_perception",
                sev,
                evidence,
                args={"lines": value, "evidence": evidence_text},
                masked=masked,
            )
        return self._diag(
            "time_perception",
            sev,
            evidence,
            args={"n": value, "evidence": evidence_text},
            template_key="diagnosis_alt",
            masked=masked,
        )

    def _ci_appeasement(self, period: list[Commit]) -> Diagnosis | None:
        hits = [c for c in period if self.re_ci.search(c.message)]
        if not hits:
            return None
        n = len(hits)
        loud = any(is_scream(c.message, self.stoplist) for c in hits)
        if n >= 6:
            sev = "IV"
        elif n >= 4 or loud:
            sev = "III"
        elif n >= 2:
            sev = "II"
        else:
            sev = "I"
        rep = next((c for c in hits if is_scream(c.message, self.stoplist)), hits[0])
        evidence_text, masked = self.mask(rep.subject)
        return self._diag(
            "ci_appeasement", sev, hits, args={"n": n, "evidence": evidence_text}, masked=masked
        )

    def _empty_commit(self, period: list[Commit]) -> Diagnosis | None:
        hits = [
            c
            for c in period
            if not c.is_merge and c.files_changed == 0 and c.insertions == 0 and c.deletions == 0
        ]
        if not hits:
            return None
        n = len(hits)
        if n >= 6:
            sev = "IV"
        elif n >= 4:
            sev = "III"
        elif n >= 2:
            sev = "II"
        else:
            sev = "I"
        evidence_text, masked = self.mask(hits[0].subject)
        return self._diag(
            "empty_commit", sev, hits, args={"n": n, "evidence": evidence_text}, masked=masked
        )

    # -- entry point ---------------------------------------------------------

    def run(
        self,
        period: list[Commit],
        window: list[Commit],
        scores: dict[str, float],
        stats: PeriodStats,
        rewrites: int | None,
        techdebt_history: dict[str, str] | None = None,
    ) -> tuple[list[Diagnosis], list[str]]:
        notes: list[str] = []
        segments = self._segments(period)

        detectors: list[Callable[[], Diagnosis | None]] = [
            lambda: self._fix_loop(segments),  # first: fills _fix_chain_shas
            lambda: self._naming_collapse(segments),
            lambda: self._decision_regret(period),
            lambda: self._emotional_outburst(period, scores),
            lambda: self._p0_incident(period),
            lambda: self._night_despair(period, stats),
            lambda: self._boundary(period, stats),
            lambda: self._anxious(period),
            lambda: self._history(rewrites, notes),
            lambda: self._alexithymia(period, stats),
            lambda: self._binge(period, window),
            lambda: self._commitment(period, stats),
            lambda: self._magical(period, scores),
            lambda: self._stockholm(period, techdebt_history),
            lambda: self._ci_appeasement(period),
            lambda: self._empty_commit(period),
            lambda: self._time_perception(period, window),  # last: reads chain shas
        ]
        diagnoses = [d for d in (fn() for fn in detectors) if d is not None]
        diagnoses.sort(key=lambda d: d.rank_key, reverse=True)
        return diagnoses, notes
