# CommitShrink

[![Tests](https://github.com/Anderson-ops-oss/CommitShrink/actions/workflows/tests.yml/badge.svg)](https://github.com/Anderson-ops-oss/CommitShrink/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/github/license/Anderson-ops-oss/CommitShrink)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

**English** | [简体中文](README.zh-CN.md)

> A perfectly serious clinical instrument that reads your `git log` and returns a developer mental-health assessment — diagnostic codes, quantitative indicators, and a prescription you will not follow.

---

## Overview

CommitShrink is a clinical assessment instrument for developers who never asked to be assessed.

It ingests your `git log`, scores the emotional trajectory of every commit message, and cross-references your commit history against an internally validated symptom taxonomy. What comes out the other end is a full diagnostic report: a primary diagnosis, a battery of quantitative indicators, verbatim clinical evidence pulled from your own commit history, and a prescription you will not follow.

The sentiment-analysis techniques underneath are not novel — this has been done before, in academic papers and weekend projects alike. What CommitShrink contributes is commitment to the bit: the diagnostic codes, the deadpan clinical prose, the fictional norm database calibrated against 10,000 fictional developers, and a two-reviewer quality control sign-off performed by one program and a copy of itself.

**A note on language.** The tool currently generates reports in Chinese — the joke was built for a Chinese-language commit culture first, and the full symptom taxonomy in [`commit_shrink/data/symptoms.yaml`](commit_shrink/data/symptoms.yaml) is written in Chinese. The excerpt below is an English rendering for readers of this document; it is not literal tool output. If you read Chinese, see [README.zh-CN.md](README.zh-CN.md), whose sample section is much closer to what you'll actually see on your screen.

## Sample Report (illustrative excerpt)

<table>
<tr><td>Patient</td><td>Demo Developer &lt;dev@example.com&gt;</td></tr>
<tr><td>Assessment Period</td><td>2026-06-22 (Mon) – 2026-06-28 (Sun)</td></tr>
<tr><td>Valid Sample</td><td>47 commits (none excluded; 18 low-information samples counted toward the alexithymia index)</td></tr>
<tr><td>Method</td><td>Non-invasive naturalistic behavioral observation (patient was unaware of the assessment during data collection; social desirability bias = 0, Hawthorne effect = 0)</td></tr>
<tr><td>Instrument</td><td>CommitShrink v0.1 · cross-cultural validity certified (n = 1) · test-retest reliability r = 1.00</td></tr>
</table>

**Chief Complaint** None. Patient reported no subjective distress and did not seek evaluation; the specimen was collected proactively by this system. Insight: partially present (see Record 1, 03:52).

**Primary Diagnosis** GIT-42.2 Compulsive Fix Disorder (severe, progressive; this period's worst single episode reached Grade IV — see Record 1)
**Secondary Diagnoses** GIT-23.5 Nocturnal Despair Tendency (moderate) | GIT-11.2 Commit Alexithymia (moderate)
**Other Clinical Concerns** GIT-70.7 Magical Thinking (single episode, see Record 3)

**Composite Mental Health Score: 34 / 100** (metric baseline 45 − diagnosis burden 11)
Down 9 points from last period; third consecutive week of decline. Extrapolating the current slope, the patient is projected to hit the scale's floor by assessment week 30.

#### Record 1 | GIT-42.2 Compulsive Fix Disorder · Severity IV (Extremely Severe)

**Episode Window** Jun 25 (Thu), 02:14 – 03:52 — 98 minutes

```
02:14  a3f9c21  fix login bug
02:31  8be0d47  fix login bug again
02:58  f10a9b3  really fix login bug
03:22  90cc1ea  PLEASE WORK
03:52  6d2e8f0  ok it was a typo
```

**Clinical Interpretation** Five interventions on the same issue within 98 minutes. Language mode progressed through four stages — statement (02:14), reiteration (02:31), emphasis (02:58), supplication (03:22) — consistent with this disorder's typical course. Grading basis: chain length 5, an all-caps sample present in the chain, and the entire episode falling within 00:00–05:59 — all three Grade IV criteria met simultaneously. Insight was recovered at 03:52 ("ok it was a typo"); recovery was accompanied by mild loss of self-esteem.

> This excerpt is drawn from the project's golden sample, [`docs/report-sample.md`](docs/report-sample.md), which defines exactly what a correct report must contain. Every number in it is reproducible from the rules in `symptoms.yaml` — generate your own with the demo repository below.

## How It Works

```
collector.py  →  analyzer.py  →  diagnoser.py  →  report.py
   git log        sentiment        symptom            render
   (1 pass)        scoring          matching
```

1. **Collector** reads your repository with a single `git log --numstat` pass — no external services, no network calls, nothing leaves your machine.
2. **Analyzer** scores every commit message's sentiment (VADER plus a hand-tuned bilingual lexicon patch) and computes the six headline metrics.
3. **Diagnoser** matches your commit patterns against a symptom table — every diagnosis, severity threshold, and prescription lives in [`commit_shrink/data/symptoms.yaml`](commit_shrink/data/symptoms.yaml) as data, not code.
4. **Report** renders the result as a full clinical write-up (a Streamlit web report is planned).

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/Anderson-ops-oss/CommitShrink.git
cd commit-shrink
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Usage

```bash
commit-shrink                                # assess the current directory, last 7 days
commit-shrink path/to/repo                   # assess a specific repository
commit-shrink . --days 30                    # widen the assessment window
commit-shrink . --author you@example.com     # assess a specific contributor
commit-shrink . --until 2026-06-28T23:59:00+08:00
```

Want to see it run without risking your own commit history? Generate a clinically rich demo repository and point the tool at it:

```bash
python scripts/make_fixture.py --path fixture-repo
```

The script builds its history around the most recently completed Mon–Sun week and prints the exact command to assess it, e.g.:

```bash
commit-shrink fixture-repo --days 7 --until 2026-06-28T23:59:00+08:00
```

Run the line it prints (the `--until` value depends on today's date) — `commit-shrink fixture-repo --days 7` on its own defaults to *today* as the window's end, which misses most of the demo history.

## A Few Diagnostic Codes

The complete taxonomy (15 conditions) lives in [`commit_shrink/data/symptoms.yaml`](commit_shrink/data/symptoms.yaml). A preview:

| Code | Condition | Trigger |
|---|---|---|
| GIT-42.2 | Compulsive Fix Disorder | `fix` → `fix again` → `really fix` → `PLEASE WORK` |
| GIT-60.1 | Naming System Collapse | `final` → `final_v2` → `final_v2_REAL_FINAL` |
| GIT-31.0 | Decision Regret Syndrome | `Revert "Revert ..."` — regret about regret |
| GIT-99.0 | Psychological Code Red | a `hotfix` at 4 AM |
| GIT-11.2 | Commit Alexithymia | a quarter of your messages just say `update` |

## Disclaimer

This report is generated automatically from `git log`. It does not constitute medical advice, though it may constitute code review advice. Every "condition" named here is a pastiche of clinical assessment language; a handful of diagnostic labels are borrowed clinical terms transplanted into the git domain — this report evaluates a commit history, not a person, and does not refer to any real mental illness or its patients.

This tool is for self-assessment. Running it against a colleague's repository without their consent produces an invalid diagnosis — and is, itself, a symptom this center has not yet coded.

## License

[MIT](LICENSE) © 2026 Anderson Cheng
