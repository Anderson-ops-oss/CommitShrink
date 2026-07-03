"""Render an Assessment as the clinical report defined by the golden sample.

Every fixed string comes from symptoms.yaml (report_copy / boilerplate / meta);
this module contains zero display-copy literals. Layout is validated against
docs/report-sample.md, Appendix B.
"""

from __future__ import annotations

from datetime import timedelta

from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .analyzer import collapse_cjk_whitespace
from .diagnoser import Diagnosis
from .history import Trend
from .pipeline import Assessment


def _copy(text: str) -> str:
    """Normalize folded-scalar whitespace in display copy from the yaml."""
    return collapse_cjk_whitespace(" ".join(str(text).split()))

SPARK_CHARS = "▁▂▃▄▅▆▇█"
EMPTY_DAY_CHAR = "·"
MAX_RECORDS = 3
MAX_PRESCRIPTIONS = 4
MAX_EVIDENCE_LINES = 6


class ReportRenderer:
    def __init__(self, cfg: dict):
        self.rc = cfg["report_copy"]
        self.bp = cfg["boilerplate"]
        self.meta = cfg["meta"]
        self.sev_labels = self.meta["severity_labels"]
        # Separator between a bold label and its value (U+3000 in zh, ": " in en).
        self.label_sep = self.rc["label_sep"]

    # -- helpers -------------------------------------------------------------

    def _percentile_text(self, metric) -> str:
        if metric.percentile is None:
            return self.rc["metrics_labels"]["no_history"]
        pct = round(metric.percentile)
        key = "percentile_above" if metric.direction == "higher_is_worse" else "percentile_below"
        return self.rc["metrics_labels"][key].format(pct=pct)

    def _diagnosis_line(self, d: Diagnosis) -> str:
        sev = self.rc["diagnosis_labels"]["severity_fmt"].format(label=self.sev_labels[d.severity])
        return f"{d.code} {d.name}{sev}"

    def _trend_note(self, trend: Trend) -> str:
        dl = self.rc["diagnosis_labels"]
        note = dl["period_delta_fmt"].format(delta=f"{trend.composite_delta:+d}")
        if trend.decline_streak >= 2 and trend.extrapolated_week is not None:
            note += dl["decline_streak_fmt"].format(n=trend.decline_streak)
            note += dl["extrapolation_fmt"].format(week=trend.extrapolated_week)
        return dl["trend_wrap_fmt"].format(note=note)

    def _evidence_lines(self, a: Assessment, d: Diagnosis) -> list[str]:
        lines = []
        for c in d.evidence[:MAX_EVIDENCE_LINES]:
            subject = a.masked_subjects.get(c.sha, c.subject)
            lines.append(f"{c.ts.strftime('%m-%d %H:%M')}  {c.short}  {subject}")
        return lines

    # -- sections ------------------------------------------------------------

    def _header(self, console: Console, a: Assessment) -> None:
        week = a.period_end.isocalendar().week
        console.print()
        console.print(Text(self.rc["center_name"], style="bold"), justify="center")
        console.print(Text(self.rc["report_title_fmt"].format(week=week)), justify="center")
        console.print()
        labels = self.rc["header_labels"]
        values = self.rc["header_values"]
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="dim", no_wrap=True)
        grid.add_column()
        grid.add_row(labels["patient"], f"{a.patient_name} <{a.patient_email}>")
        grid.add_row(
            labels["period"],
            f"{a.period_start.strftime('%Y-%m-%d')} — {a.period_end.strftime('%Y-%m-%d')}",
        )
        grid.add_row(
            labels["sample"],
            values["sample_fmt"].format(n=a.stats.total, low_info=a.stats.low_info_count),
        )
        grid.add_row(labels["method"], values["method"])
        grid.add_row(labels["instrument"], values["instrument"])
        grid.add_row(
            labels["report_date"],
            a.generated_at.strftime("%Y-%m-%d %H:%M") + values["report_date_suffix"],
        )
        grid.add_row(
            labels["report_no"],
            values["report_no_fmt"].format(year=a.period_end.year, week=week),
        )
        console.print(grid)

    def _diagnosis_section(self, console: Console, a: Assessment, trend: Trend | None = None) -> None:
        dl = self.rc["diagnosis_labels"]
        console.print(Rule(self.rc["sections"]["diagnosis"], align="left"))
        console.print(f"[bold]{dl['chief_complaint']}[/bold]{self.label_sep}{dl['chief_complaint_text']}")
        console.print()
        if not a.diagnoses:
            console.print(dl["none_confirmed"])
            if a.notes:
                console.print(f"[bold]{dl['other']}[/bold]{self.label_sep}{dl['list_join'].join(a.notes)}")
        else:
            primary, secondary, others = a.diagnoses[0], a.diagnoses[1:3], a.diagnoses[3:]
            console.print(f"[bold]{dl['primary']}[/bold]{self.label_sep}{self._diagnosis_line(primary)}")
            if secondary:
                joined = dl["secondary_join"].join(self._diagnosis_line(d) for d in secondary)
                console.print(f"[bold]{dl['secondary']}[/bold]{self.label_sep}{joined}")
            other_parts = [f"{d.code} {d.name}" for d in others] + a.notes
            if other_parts:
                console.print(f"[bold]{dl['other']}[/bold]{self.label_sep}{dl['list_join'].join(other_parts)}")
        console.print()
        composite = a.metrics["composite_score"]
        console.print(f"[bold]{dl['composite_fmt'].format(score=composite.display)}[/bold]")
        if trend and trend.composite_delta is not None:
            console.print(self._trend_note(trend))
        console.print()
        allcaps_note = (
            dl["allcaps_note_fmt"].format(u=a.stats.uppercase_count)
            if a.stats.uppercase_count and a.stats.uppercase_all_night
            else ""
        )
        impression = dl["impression_fmt"].format(
            n=a.stats.total, night=a.stats.night_count, allcaps_note=allcaps_note
        )
        console.print(f"[bold]{dl['impression']}[/bold]{self.label_sep}{impression}")

    def _metrics_section(self, console: Console, a: Assessment, trend: Trend | None = None) -> None:
        ml = self.rc["metrics_labels"]
        console.print(Rule(self.rc["sections"]["metrics"], align="left"))
        table = Table(show_edge=False, pad_edge=False)
        for h in ml["headers"]:
            table.add_column(h)
        display_ids = [
            "night_despair_index",
            "boundary_integrity",
            "emotional_baseline",
            "fix_loop_density",
            "alexithymia_index",
        ]
        previous = trend.metric_previous if trend else {}
        for mid in display_ids:
            m = a.metrics[mid]
            value = m.display
            if m.healthy:
                value = f"{m.display}*"
            prev_text = previous.get(mid, ml["no_history"])
            table.add_row(m.name, f"[bold]{value}[/bold]", prev_text, m.reference, self._percentile_text(m))
        console.print(table)
        if not previous:
            console.print(Text(ml["first_assessment_note"], style="dim"))
        console.print(Text(_copy(self.meta["norms_disclaimer"]), style="dim"))
        if any(a.metrics[mid].healthy for mid in display_ids):
            console.print(Text(f"* {self.bp['healthy_copy']}", style="dim"))

    def _records_section(self, console: Console, a: Assessment) -> None:
        rl = self.rc["records_labels"]
        console.print(Rule(self.rc["sections"]["records"], align="left"))
        records = [d for d in a.diagnoses if d.evidence][:MAX_RECORDS]
        for i, d in enumerate(records, start=1):
            title = rl["record_fmt"].format(
                i=i, code=d.code, name=d.name, sev=d.severity, sev_label=self.sev_labels[d.severity]
            )
            console.print(f"[bold]{title}[/bold]")
            first, last = d.evidence[0], d.evidence[-1]
            span = first.ts.strftime("%m-%d %H:%M")
            if last.ts != first.ts:
                span += f" – {last.ts.strftime('%H:%M' if last.ts.date() == first.ts.date() else '%m-%d %H:%M')}"
            console.print(f"[dim]{rl['time_span']}[/dim]{self.label_sep}{span}")
            for line in self._evidence_lines(a, d):
                console.print(Text(f"    {line}", style="cyan"))
            evidence_masked = any(
                a.masked_subjects.get(c.sha, c.subject) != c.subject
                for c in d.evidence[:MAX_EVIDENCE_LINES]
            )
            interpretation = d.text + (rl["masking_note"] if d.masked or evidence_masked else "")
            console.print(f"[dim]{rl['interpretation']}[/dim]{self.label_sep}{interpretation}")
            console.print()

    def _ekg_section(self, console: Console, a: Assessment) -> None:
        el = self.rc["ekg_labels"]
        console.print(Rule(self.rc["sections"]["ekg"], align="left"))
        n_days = max(1, (a.period_end.date() - a.period_start.date()).days + 1)
        table = Table(show_edge=False, pad_edge=False, show_header=True)
        cells: list[str] = []
        headers: list[str] = []
        tz = a.period_end.tzinfo
        for offset in range(n_days):
            day = a.period_start.date() + timedelta(days=offset)
            # Bucket in the report's timezone so eastward author timestamps
            # cannot fall outside the rendered columns.
            day_scores = [
                a.scores[c.sha] for c in a.commits if c.ts.astimezone(tz).date() == day
            ]
            headers.append(day.strftime("%m-%d"))
            if day_scores:
                avg = sum(day_scores) / len(day_scores)
                idx = min(len(SPARK_CHARS) - 1, max(0, round((avg + 1) / 2 * (len(SPARK_CHARS) - 1))))
                cells.append(SPARK_CHARS[idx] * 3)
            else:
                cells.append(EMPTY_DAY_CHAR)
        for h in headers:
            table.add_column(h, justify="center")
        table.add_row(*cells)
        console.print(table)
        trough_sha = min(a.scores, key=a.scores.get)
        trough = next(c for c in a.commits if c.sha == trough_sha)
        console.print(
            el["trough_fmt"].format(
                time=trough.ts.strftime("%m-%d %H:%M"),
                evidence=a.masked_subjects.get(trough.sha, trough.subject),
                score=f"{a.scores[trough_sha]:+.2f}",
            )
        )

    def _prescriptions_section(self, console: Console, a: Assessment) -> None:
        pl = self.rc["prescriptions_labels"]
        console.print(Rule(self.rc["sections"]["prescriptions"], align="left"))
        items = [d.prescription for d in a.diagnoses[:MAX_PRESCRIPTIONS]]
        items.append(pl["social_support"])
        items.append(pl["referral"])
        for i, item in enumerate(items, start=1):
            console.print(f"{i}. {item}")

    def _disclaimer_section(self, console: Console) -> None:
        fl = self.rc["footer_labels"]
        console.print(Rule(self.rc["sections"]["disclaimer"], align="left"))
        console.print(Text(_copy(self.bp["disclaimer"])))
        console.print()
        console.print(f"[bold]{fl['followup']}[/bold]{self.label_sep}{fl['followup_value']}")
        console.print(f"[bold]{fl['qa']}[/bold]{self.label_sep}{self.bp['qa_note']}")
        console.print(f"[bold]{fl['attending']}[/bold]{self.label_sep}{fl['attending_value']}")
        console.print()

    # -- entry point -----------------------------------------------------------

    def render(self, console: Console, a: Assessment, trend: Trend | None = None) -> None:
        self._header(console, a)
        self._diagnosis_section(console, a, trend)
        self._metrics_section(console, a, trend)
        self._records_section(console, a)
        self._ekg_section(console, a)
        self._prescriptions_section(console, a)
        self._disclaimer_section(console)
