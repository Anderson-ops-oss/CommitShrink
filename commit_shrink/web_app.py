"""Streamlit shell for CommitShrink.

Run with: streamlit run commit_shrink/web_app.py

An input form drives the exact same assess_repo() pipeline the CLI uses,
with the same error handling. All display copy comes from symptoms.yaml's
report_copy/boilerplate/meta (same source the terminal renderer reads) -
this module contains zero display-copy literals. Wherever report.py's
ReportRenderer already computes shared presentation logic (percentile text,
diagnosis line formatting, masked evidence lines), this module reuses that
same ReportRenderer instance instead of re-deriving it, so the two
renderers cannot drift apart.

Uses absolute imports (not the package's usual relative style) because
`streamlit run` executes this file directly, outside package context.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from commit_shrink.analyzer import collapse_cjk_whitespace
from commit_shrink.collector import NotARepoError
from commit_shrink.pipeline import Assessment, NoCommitsError, assess_repo, load_config
from commit_shrink.report import MAX_EVIDENCE_LINES, MAX_PRESCRIPTIONS, MAX_RECORDS, ReportRenderer

DISPLAY_METRIC_IDS = [
    "night_despair_index",
    "boundary_integrity",
    "emotional_baseline",
    "fix_loop_density",
    "alexithymia_index",
]


def _copy(text: str) -> str:
    """Normalize folded-scalar whitespace in display copy from the yaml."""
    return collapse_cjk_whitespace(" ".join(str(text).split()))


def render_header(assessment: Assessment, cfg: dict) -> None:
    rc = cfg["report_copy"]
    labels = rc["header_labels"]
    values = rc["header_values"]
    week = assessment.period_end.isocalendar().week

    st.subheader(rc["report_title_fmt"].format(week=week))
    rows = [
        (labels["patient"], f"{assessment.patient_name} <{assessment.patient_email}>"),
        (
            labels["period"],
            f"{assessment.period_start:%Y-%m-%d} — {assessment.period_end:%Y-%m-%d}",
        ),
        (
            labels["sample"],
            values["sample_fmt"].format(
                n=assessment.stats.total, low_info=assessment.stats.low_info_count
            ),
        ),
        (labels["method"], values["method"]),
        (labels["instrument"], values["instrument"]),
        (
            labels["report_date"],
            assessment.generated_at.strftime("%Y-%m-%d %H:%M") + values["report_date_suffix"],
        ),
        (
            labels["report_no"],
            values["report_no_fmt"].format(year=assessment.period_end.year, week=week),
        ),
    ]
    for label, value in rows:
        st.markdown(f"**{label}**　{value}")


def render_diagnosis_section(assessment: Assessment, cfg: dict, renderer: ReportRenderer) -> None:
    rc = cfg["report_copy"]
    dl = rc["diagnosis_labels"]

    st.subheader(rc["sections"]["diagnosis"])
    st.markdown(f"**{dl['chief_complaint']}**　{dl['chief_complaint_text']}")

    diagnoses = assessment.diagnoses
    if not diagnoses:
        st.markdown(dl["none_confirmed"])
        if assessment.notes:
            st.markdown(f"**{dl['other']}**　{'；'.join(assessment.notes)}")
    else:
        primary, secondary, others = diagnoses[0], diagnoses[1:3], diagnoses[3:]
        st.markdown(f"**{dl['primary']}**　{renderer._diagnosis_line(primary)}")
        if secondary:
            joined = " ｜ ".join(renderer._diagnosis_line(d) for d in secondary)
            st.markdown(f"**{dl['secondary']}**　{joined}")
        other_parts = [f"{d.code} {d.name}" for d in others] + assessment.notes
        if other_parts:
            st.markdown(f"**{dl['other']}**　{'；'.join(other_parts)}")

    composite = assessment.metrics["composite_score"]
    st.markdown(f"**{dl['composite_fmt'].format(score=composite.display)}**")

    allcaps_note = (
        dl["allcaps_note_fmt"].format(u=assessment.stats.uppercase_count)
        if assessment.stats.uppercase_count and assessment.stats.uppercase_all_night
        else ""
    )
    impression = dl["impression_fmt"].format(
        n=assessment.stats.total, night=assessment.stats.night_count, allcaps_note=allcaps_note
    )
    st.markdown(f"**{dl['impression']}**　{impression}")


def render_metrics_section(assessment: Assessment, cfg: dict, renderer: ReportRenderer) -> None:
    rc = cfg["report_copy"]
    bp = cfg["boilerplate"]
    ml = rc["metrics_labels"]
    headers = ml["headers"]

    st.subheader(rc["sections"]["metrics"])
    rows = []
    for mid in DISPLAY_METRIC_IDS:
        m = assessment.metrics[mid]
        value = f"{m.display}*" if m.healthy else m.display
        rows.append(
            {
                headers[0]: m.name,
                headers[1]: value,
                headers[2]: ml["no_history"],
                headers[3]: m.reference,
                headers[4]: renderer._percentile_text(m),
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption(ml["first_assessment_note"])
    st.caption(_copy(cfg["meta"]["norms_disclaimer"]))
    if any(assessment.metrics[mid].healthy for mid in DISPLAY_METRIC_IDS):
        st.caption(f"* {bp['healthy_copy']}")


def render_records_section(assessment: Assessment, cfg: dict, renderer: ReportRenderer) -> None:
    rc = cfg["report_copy"]
    rl = rc["records_labels"]
    sev_labels = cfg["meta"]["severity_labels"]

    st.subheader(rc["sections"]["records"])
    records = [d for d in assessment.diagnoses if d.evidence][:MAX_RECORDS]
    for i, d in enumerate(records, start=1):
        title = rl["record_fmt"].format(
            i=i, code=d.code, name=d.name, sev=d.severity, sev_label=sev_labels[d.severity]
        )
        with st.expander(title, expanded=(i == 1)):
            first, last = d.evidence[0], d.evidence[-1]
            span = first.ts.strftime("%m-%d %H:%M")
            if last.ts != first.ts:
                same_day = last.ts.date() == first.ts.date()
                span += f" – {last.ts.strftime('%H:%M' if same_day else '%m-%d %H:%M')}"
            st.caption(f"{rl['time_span']}　{span}")

            st.code("\n".join(renderer._evidence_lines(assessment, d)))

            evidence_masked = any(
                assessment.masked_subjects.get(c.sha, c.subject) != c.subject
                for c in d.evidence[:MAX_EVIDENCE_LINES]
            )
            interpretation = d.text + (rl["masking_note"] if d.masked or evidence_masked else "")
            st.markdown(f"**{rl['interpretation']}**　{interpretation}")


def render_ekg_chart(assessment: Assessment, cfg: dict) -> None:
    """Per-commit sentiment line chart: the interactive upgrade over the
    terminal report's daily-average sparkline (see report.py::_ekg_section,
    which this mirrors for the trough caption via the same yaml copy).
    """
    rc = cfg["report_copy"]
    el = rc["ekg_labels"]
    st.subheader(rc["sections"]["ekg"])

    tz = assessment.period_end.tzinfo
    commits = sorted(assessment.commits, key=lambda c: c.ts)

    xs = [c.ts.astimezone(tz) for c in commits]
    ys = [assessment.scores[c.sha] for c in commits]
    hover = [
        f"<b>{assessment.masked_subjects.get(c.sha, c.subject)}</b><br>"
        f"{c.short}  ·  {c.ts.astimezone(tz):%m-%d %H:%M}<br>"
        f"{assessment.scores[c.sha]:+.2f}"
        for c in commits
    ]

    trough_sha = min(assessment.scores, key=assessment.scores.get)
    trough = next(c for c in commits if c.sha == trough_sha)
    trough_idx = commits.index(trough)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            name=el["legend_commits"],
            hovertext=hover,
            hoverinfo="text",
            line=dict(color="#5B8DEF"),
            marker=dict(size=6),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[xs[trough_idx]],
            y=[ys[trough_idx]],
            mode="markers",
            name=el["legend_trough"],
            hovertext=[hover[trough_idx]],
            hoverinfo="text",
            marker=dict(size=13, color="#E4572E", symbol="diamond"),
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.4)
    fig.update_layout(
        xaxis_title=el["x_axis"],
        yaxis_title=el["y_axis"],
        yaxis_range=[-1.05, 1.05],
        hovermode="closest",
        margin=dict(l=10, r=10, t=10, b=10),
        height=360,
    )
    st.plotly_chart(fig, width="stretch")

    st.caption(
        el["trough_fmt"].format(
            time=trough.ts.strftime("%m-%d %H:%M"),
            evidence=assessment.masked_subjects.get(trough.sha, trough.subject),
            score=f"{assessment.scores[trough.sha]:+.2f}",
        )
    )


def render_prescriptions_section(assessment: Assessment, cfg: dict) -> None:
    rc = cfg["report_copy"]
    pl = rc["prescriptions_labels"]

    st.subheader(rc["sections"]["prescriptions"])
    items = [d.prescription for d in assessment.diagnoses[:MAX_PRESCRIPTIONS]]
    items.append(pl["social_support"])
    items.append(pl["referral"])
    for i, item in enumerate(items, start=1):
        st.markdown(f"{i}. {item}")


def render_disclaimer_section(cfg: dict) -> None:
    rc = cfg["report_copy"]
    bp = cfg["boilerplate"]
    fl = rc["footer_labels"]

    st.subheader(rc["sections"]["disclaimer"])
    st.markdown(_copy(bp["disclaimer"]))
    st.markdown(f"**{fl['followup']}**　{fl['followup_value']}")
    st.markdown(f"**{fl['qa']}**　{bp['qa_note']}")
    st.markdown(f"**{fl['attending']}**　{fl['attending_value']}")


def render_report(assessment: Assessment, cfg: dict) -> None:
    renderer = ReportRenderer(cfg)
    render_header(assessment, cfg)
    st.divider()
    render_diagnosis_section(assessment, cfg, renderer)
    st.divider()
    render_metrics_section(assessment, cfg, renderer)
    st.divider()
    render_records_section(assessment, cfg, renderer)
    st.divider()
    render_ekg_chart(assessment, cfg)
    st.divider()
    render_prescriptions_section(assessment, cfg)
    st.divider()
    render_disclaimer_section(cfg)


if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
if "assessment" not in st.session_state:
    st.session_state.assessment = None

cfg = st.session_state.cfg
rc = cfg["report_copy"]

st.set_page_config(page_title="CommitShrink", page_icon=":stethoscope:")
st.title(rc["center_name"])

with st.form("assessment_form"):
    path_input = st.text_input("Repository path", value=".")
    days_input = st.number_input("Assessment window (days)", min_value=1, value=7, step=1)
    author_input = st.text_input("Author filter (optional, matches git --author)", value="")
    until_input = st.text_input(
        "End of assessment period (optional, ISO datetime; defaults to now)", value=""
    )
    submitted = st.form_submit_button("Run Assessment")

if submitted:
    try:
        until = datetime.fromisoformat(until_input).astimezone() if until_input.strip() else None
    except ValueError:
        st.error(f"'{until_input}' is not a valid ISO datetime.")
    else:
        with st.spinner("Reading git log and generating the assessment..."):
            try:
                assessment = assess_repo(
                    Path(path_input),
                    days=int(days_input),
                    until=until,
                    author=author_input.strip() or None,
                    cfg=cfg,
                )
            except NotARepoError:
                st.error(rc["errors"]["not_a_repo"])
            except NoCommitsError:
                st.error(rc["errors"]["no_commits"])
            except RuntimeError as e:
                st.error(str(e))
            else:
                st.session_state.assessment = assessment

assessment = st.session_state.assessment
if assessment is not None:
    render_report(assessment, cfg)
