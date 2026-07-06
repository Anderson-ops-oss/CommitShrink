"""Render an Assessment as GitHub-Flavored Markdown -- the fourth presentation
surface alongside the terminal report (report.py), the shareable HTML card
(card.py), and the Streamlit app (web_app.py).

This is the engine behind the "live" sample report embedded in README.md /
README.zh-CN.md (see scripts/update_readme_examples.py): a scheduled GitHub
Action runs `commit-shrink . --markdown ...` against this repo's own git log
and splices the result straight into the README, so the sample stays real
instead of a static mock.

Every section mirrors ReportRenderer.render()'s terminal output one-for-one
(same order, same underlying label/copy lookups), translated from Rich
console calls into GFM markup. Nothing here is display-copy: every string
comes from `ReportRenderer`/`cfg`, exactly like report.py/card.py/web_app.py,
so this rendering can't drift from the other three.
"""

from __future__ import annotations

from datetime import timedelta

from .diagnoser import Diagnosis
from .history import Trend
from .pipeline import Assessment
from .report import (
    EMPTY_DAY_CHAR,
    MAX_EVIDENCE_LINES,
    MAX_PRESCRIPTIONS,
    MAX_RECORDS,
    SPARK_CHARS,
    ReportRenderer,
    _copy,
)

_DISPLAY_METRIC_IDS = [
    "night_despair_index",
    "boundary_integrity",
    "emotional_baseline",
    "fix_loop_density",
    "alexithymia_index",
]


def _cell(value) -> str:
    """Escape a value for a GFM table cell -- `|` would otherwise split the
    row early. The only values here that are arbitrary (not config-driven)
    copy are the patient's git author name/email."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _header_md(renderer: ReportRenderer, a: Assessment) -> str:
    rc = renderer.rc
    labels, values = rc["header_labels"], rc["header_values"]
    week = a.period_end.isocalendar().week
    rows = [
        (labels["patient"], f"{a.patient_name} <{a.patient_email}>"),
        (labels["period"], f"{a.period_start:%Y-%m-%d} — {a.period_end:%Y-%m-%d}"),
        (
            labels["sample"],
            values["sample_fmt"].format(n=a.stats.total, low_info=a.stats.low_info_count),
        ),
        (labels["method"], values["method"]),
        (labels["instrument"], values["instrument"]),
        (
            labels["report_date"],
            a.generated_at.strftime("%Y-%m-%d %H:%M") + values["report_date_suffix"],
        ),
        (labels["report_no"], values["report_no_fmt"].format(year=a.period_end.year, week=week)),
    ]
    table_rows = "\n".join(f"| {_cell(k)} | {_cell(v)} |" for k, v in rows)
    return (
        f"## {rc['center_name']}\n\n"
        f"**{rc['report_title_fmt'].format(week=week)}**\n\n"
        f"| | |\n|---|---|\n{table_rows}"
    )


def _diagnosis_section_md(renderer: ReportRenderer, a: Assessment, trend: Trend | None) -> str:
    rc = renderer.rc
    dl = rc["diagnosis_labels"]
    sep = renderer.label_sep
    lines = [f"### {rc['sections']['diagnosis']}", ""]
    lines.append(f"**{dl['chief_complaint']}**{sep}{dl['chief_complaint_text']}")
    lines.append("")
    if not a.diagnoses:
        lines.append(dl["none_confirmed"])
        if a.notes:
            lines.append(f"**{dl['other']}**{sep}{dl['list_join'].join(renderer.rendered_notes(a))}")
    else:
        primary, secondary, others = a.diagnoses[0], a.diagnoses[1:3], a.diagnoses[3:]
        lines.append(f"**{dl['primary']}**{sep}{renderer._diagnosis_line(primary)}")
        if secondary:
            joined = dl["secondary_join"].join(renderer._diagnosis_line(d) for d in secondary)
            lines.append(f"**{dl['secondary']}**{sep}{joined}")
        other_parts = [f"{d.code} {renderer.diagnosis_name(d)}" for d in others] + renderer.rendered_notes(a)
        if other_parts:
            lines.append(f"**{dl['other']}**{sep}{dl['list_join'].join(other_parts)}")
    lines.append("")
    composite = a.metrics["composite_score"]
    composite_line = f"**{dl['composite_fmt'].format(score=composite.display)}**"
    if trend and trend.composite_delta is not None:
        composite_line += f"\n{renderer._trend_note(trend)}"
    lines.append(composite_line)
    lines.append("")
    allcaps_note = (
        dl["allcaps_note_fmt"].format(u=a.stats.uppercase_count)
        if a.stats.uppercase_count and a.stats.uppercase_all_night
        else ""
    )
    impression = dl["impression_fmt"].format(
        n=a.stats.total, night=a.stats.night_count, allcaps_note=allcaps_note
    )
    lines.append(f"**{dl['impression']}**{sep}{impression}")
    return "\n".join(lines)


def _metrics_section_md(renderer: ReportRenderer, a: Assessment, trend: Trend | None) -> str:
    rc = renderer.rc
    ml = rc["metrics_labels"]
    previous = trend.metric_previous if trend else {}
    header_row = " | ".join(ml["headers"])
    align_row = " | ".join("---" for _ in ml["headers"])
    rows = []
    for mid in _DISPLAY_METRIC_IDS:
        m = a.metrics[mid]
        spec = renderer.metrics_spec[mid]
        value = f"{m.display}*" if m.healthy else m.display
        prev_text = previous.get(mid, ml["no_history"])
        rows.append(
            f"| {_cell(spec['name'])} | **{_cell(value)}** | {_cell(prev_text)} "
            f"| {_cell(spec['reference'])} | {_cell(renderer._percentile_text(m))} |"
        )
    footnotes = []
    if not previous:
        footnotes.append(ml["first_assessment_note"])
    footnotes.append(_copy(renderer.meta["norms_disclaimer"]))
    if any(a.metrics[mid].healthy for mid in _DISPLAY_METRIC_IDS):
        footnotes.append(f"* {renderer.bp['healthy_copy']}")
    footnote_block = "\n".join(f"<sub>{f}</sub>" for f in footnotes)
    return (
        f"### {rc['sections']['metrics']}\n\n"
        f"| {header_row} |\n| {align_row} |\n" + "\n".join(rows) + f"\n\n{footnote_block}"
    )


def _record_md(renderer: ReportRenderer, a: Assessment, i: int, d: Diagnosis) -> str:
    rc = renderer.rc
    rl = rc["records_labels"]
    sep = renderer.label_sep
    title = rl["record_fmt"].format(
        i=i, code=d.code, name=renderer.diagnosis_name(d), sev=d.severity,
        sev_label=renderer.sev_labels[d.severity],
    )
    first, last = d.evidence[0], d.evidence[-1]
    span = first.ts.strftime("%m-%d %H:%M")
    if last.ts != first.ts:
        same_day = last.ts.date() == first.ts.date()
        span += f" – {last.ts.strftime('%H:%M' if same_day else '%m-%d %H:%M')}"
    evidence_lines = renderer._evidence_lines(a, d)
    evidence_masked = any(
        a.masked_subjects.get(c.sha, c.subject) != c.subject for c in d.evidence[:MAX_EVIDENCE_LINES]
    )
    interpretation = renderer.diagnosis_text(d) + (rl["masking_note"] if d.masked or evidence_masked else "")
    evidence_block = "\n".join(evidence_lines)
    return (
        f"#### {title}\n\n"
        f"**{rl['time_span']}**{sep}{span}\n\n"
        f"```\n{evidence_block}\n```\n\n"
        f"**{rl['interpretation']}**{sep}{interpretation}"
    )


def _records_section_md(renderer: ReportRenderer, a: Assessment) -> str:
    rc = renderer.rc
    records = [d for d in a.diagnoses if d.evidence][:MAX_RECORDS]
    blocks = [f"### {rc['sections']['records']}"]
    blocks.extend(_record_md(renderer, a, i, d) for i, d in enumerate(records, start=1))
    return "\n\n".join(blocks)


def _ekg_section_md(renderer: ReportRenderer, a: Assessment) -> str:
    rc = renderer.rc
    el = rc["ekg_labels"]
    n_days = max(1, (a.period_end.date() - a.period_start.date()).days + 1)
    tz = a.period_end.tzinfo
    headers, cells = [], []
    for offset in range(n_days):
        day = a.period_start.date() + timedelta(days=offset)
        day_scores = [a.scores[c.sha] for c in a.commits if c.ts.astimezone(tz).date() == day]
        headers.append(day.strftime("%m-%d"))
        if day_scores:
            avg = sum(day_scores) / len(day_scores)
            idx = min(len(SPARK_CHARS) - 1, max(0, round((avg + 1) / 2 * (len(SPARK_CHARS) - 1))))
            cells.append(SPARK_CHARS[idx] * 3)
        else:
            cells.append(EMPTY_DAY_CHAR)
    trough_sha = min(a.scores, key=a.scores.get)
    trough = next(c for c in a.commits if c.sha == trough_sha)
    trough_note = el["trough_fmt"].format(
        time=trough.ts.strftime("%m-%d %H:%M"),
        evidence=a.masked_subjects.get(trough.sha, trough.subject),
        score=f"{a.scores[trough_sha]:+.2f}",
    )
    header_row = " | ".join(headers)
    align_row = " | ".join(":---:" for _ in headers)
    cell_row = " | ".join(cells)
    return (
        f"### {rc['sections']['ekg']}\n\n"
        f"| {header_row} |\n| {align_row} |\n| {cell_row} |\n\n{trough_note}"
    )


def _prescriptions_section_md(renderer: ReportRenderer, a: Assessment) -> str:
    rc = renderer.rc
    pl = rc["prescriptions_labels"]
    items = [renderer.diagnosis_prescription(d) for d in a.diagnoses[:MAX_PRESCRIPTIONS]]
    items.append(pl["social_support"])
    items.append(pl["referral"])
    body = "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))
    return f"### {rc['sections']['prescriptions']}\n\n{body}"


def _disclaimer_section_md(renderer: ReportRenderer) -> str:
    rc = renderer.rc
    fl = rc["footer_labels"]
    sep = renderer.label_sep
    return (
        f"### {rc['sections']['disclaimer']}\n\n"
        f"{_copy(renderer.bp['disclaimer'])}\n\n"
        f"**{fl['followup']}**{sep}{fl['followup_value']}\n"
        f"**{fl['qa']}**{sep}{renderer.bp['qa_note']}\n"
        f"**{fl['attending']}**{sep}{fl['attending_value']}"
    )


def render_report_markdown(assessment: Assessment, cfg: dict, trend: Trend | None = None) -> str:
    """Render `assessment` as a self-contained GitHub-Flavored Markdown document,
    mirroring the section set and order of ReportRenderer.render() (see
    docs/report-sample.md for the target layout)."""
    renderer = ReportRenderer(cfg)
    sections = [
        _header_md(renderer, assessment),
        _diagnosis_section_md(renderer, assessment, trend),
        _metrics_section_md(renderer, assessment, trend),
        _records_section_md(renderer, assessment),
        _ekg_section_md(renderer, assessment),
        _prescriptions_section_md(renderer, assessment),
        _disclaimer_section_md(renderer),
    ]
    return "\n\n---\n\n".join(sections) + "\n"
