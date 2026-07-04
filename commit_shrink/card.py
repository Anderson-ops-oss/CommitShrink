"""Render an Assessment as a one-page shareable "discharge summary" card.

A self-contained HTML document -- inline CSS, no external fonts/images/scripts,
no image-rendering dependency -- styled like a clinical discharge summary: the
composite Mental Health Index as a gauge, the primary diagnosis code, one
prescription line, and an invitation to run your own screening. It is the most
shareable artifact CommitShrink produces: open it in a browser and screenshot,
or embed it in the web app.

Every display string comes from the config (report_copy.card) and the shared
ReportRenderer (diagnosis name / prescription), so the card is bilingual and
cannot drift from the full report.
"""

from __future__ import annotations

import html

from .pipeline import Assessment
from .report import ReportRenderer


def _mask_email(email: str) -> str:
    """a***n@host: keep the first and last local-part char, redact the rest;
    a two-char-or-shorter local part is reduced to its first char + '*'."""
    local, sep, domain = email.partition("@")
    if len(local) <= 2:
        masked = (local[:1] or "*") + "*"
    else:
        masked = f"{local[0]}***{local[-1]}"
    return f"{masked}{sep}{domain}"


def build_card_model(assessment: Assessment, renderer: ReportRenderer) -> dict:
    """Pull the card's fields through the same ReportRenderer the full report
    uses, so the two can't disagree. Returns a language-resolved, render-ready
    dict (no Assessment/Diagnosis objects leak past this seam)."""
    rc = renderer.rc
    card = rc["card"]
    week = assessment.period_end.isocalendar().week
    if assessment.diagnoses:
        primary = assessment.diagnoses[0]
        dx = f"{primary.code} {renderer.diagnosis_name(primary)}"
        rx = renderer.diagnosis_prescription(primary)
    else:
        dx = card["none_dx"]
        rx = ""
    score = assessment.metrics["composite_score"].display
    return {
        "center_name": rc["center_name"],
        "case_no": rc["header_values"]["report_no_fmt"].format(
            year=assessment.period_end.year, week=week
        ),
        "subject": _mask_email(assessment.patient_email),
        "score": score,
        "score_pct": max(0, min(100, int(float(score)))),
        "dx": dx,
        "rx": rx,
        "labels": {
            "index": card["index_label"],
            "case": card["case_label"],
            "subject": card["subject_label"],
            "primary": card["primary_label"],
            "rx": card["rx_label"],
            "footer": card["footer"],
        },
    }


def render_card_html(model: dict) -> str:
    """A self-contained HTML card. No external fonts/images/scripts, so it
    renders identically offline and is safe to embed in a sandboxed iframe."""
    e = html.escape
    lab = model["labels"]
    rx_block = (
        f'<div class="rx"><span class="k">{e(lab["rx"])}</span>'
        f'<span class="v">{e(model["rx"])}</span></div>'
        if model["rx"]
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 16px; background: #ecece4; }}
  .cs-card {{
    box-sizing: border-box; width: 380px; margin: 0 auto; padding: 26px 28px;
    font-family: Georgia, "Songti SC", "Noto Serif CJK SC", "Noto Serif", serif;
    background: #fbfbf7; color: #1a1a1a; border: 1px solid #cfcfc4;
    box-shadow: 0 2px 10px rgba(0,0,0,.10);
  }}
  .cs-card * {{ box-sizing: border-box; }}
  .cs-hd {{ text-align: center; border-bottom: 2px solid #1a1a1a; padding-bottom: 10px; }}
  .cs-hd .name {{ font-size: 15px; font-weight: 700; line-height: 1.35; }}
  .cs-meta {{ font-size: 11px; color: #555; margin-top: 12px;
             font-family: "Courier New", monospace; }}
  .cs-gauge {{ margin: 20px 0 6px; }}
  .cs-gauge .lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #555; }}
  .cs-track {{ position: relative; height: 26px; background: #e6e6dd;
              border: 1px solid #b9b9ac; margin-top: 6px; }}
  .cs-fill {{ height: 100%; background: repeating-linear-gradient(45deg,
             #2b2b2b, #2b2b2b 6px, #3a3a3a 6px, #3a3a3a 12px); }}
  .cs-score {{ position: absolute; right: 8px; top: 3px; font-size: 15px;
              font-weight: 700; color: #fff; mix-blend-mode: difference; }}
  .cs-dx {{ margin-top: 16px; }}
  .k {{ display: block; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #666; }}
  .v {{ display: block; font-size: 14px; font-weight: 700; margin-top: 2px; }}
  .rx {{ margin-top: 12px; }}
  .rx .v {{ font-weight: 400; font-style: italic; }}
  .cs-ft {{ margin-top: 20px; border-top: 1px dashed #999; padding-top: 12px; text-align: center; }}
  .cs-bar {{ height: 34px; background: repeating-linear-gradient(90deg,
            #111 0, #111 2px, #fff 2px, #fff 3px, #111 3px, #111 6px, #fff 6px, #fff 8px); }}
  .cs-ft .inv {{ font-size: 11px; color: #555; margin-top: 8px; }}
</style></head>
<body>
<div class="cs-card">
  <div class="cs-hd"><div class="name">{e(model["center_name"])}</div></div>
  <div class="cs-meta">{e(lab["case"])} {e(model["case_no"])}</div>
  <div class="cs-meta">{e(lab["subject"])}: {e(model["subject"])}</div>
  <div class="cs-gauge">
    <span class="lbl">{e(lab["index"])}</span>
    <div class="cs-track"><div class="cs-fill" style="width:{model["score_pct"]}%"></div>
      <span class="cs-score">{e(str(model["score"]))} / 100</span></div>
  </div>
  <div class="cs-dx"><span class="k">{e(lab["primary"])}</span><span class="v">{e(model["dx"])}</span></div>
  {rx_block}
  <div class="cs-ft"><div class="cs-bar"></div><div class="inv">{e(lab["footer"])}</div></div>
</div>
</body></html>"""
