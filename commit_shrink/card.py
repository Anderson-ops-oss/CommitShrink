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
import re

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
        "lang": renderer.lang,
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


def _is_wide(ch: str) -> bool:
    """CJK / fullwidth glyphs occupy roughly a full em; Latin about half.
    Used only to estimate line width for SVG word-wrap (no font metrics)."""
    return ord(ch) >= 0x2E80


def _display_width(text: str) -> float:
    return sum(1.0 if _is_wide(ch) else 0.5 for ch in text)


_TOKEN_RE = re.compile(r"[⺀-﫿＀-￯]|[^\s⺀-﫿＀-￯]+\s*|\s+")


def _wrap(text: str, budget: float, max_lines: int) -> list[str]:
    """Greedy width-aware wrap: Latin breaks on spaces, CJK breaks per glyph.
    Overflow past max_lines is truncated with an ellipsis on the last line."""
    lines: list[str] = []
    line = ""
    tokens = _TOKEN_RE.findall(text)
    truncated = False
    for token in tokens:
        candidate = line + token
        if _display_width(candidate) > budget and line.strip():
            lines.append(line.rstrip())
            line = "" if token.isspace() else token
            if len(lines) == max_lines:
                truncated = True
                break
        else:
            line = candidate
    if not truncated and line.strip() and len(lines) < max_lines:
        lines.append(line.rstrip())
    if truncated:
        last = lines[-1]
        while last and _display_width(last + "…") > budget:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def render_card_svg(model: dict) -> str:
    """A self-contained, landscape (1200x630) SVG version of the discharge-summary
    card -- a real image format that GitHub renders inline and that rasterizes to
    a standard Open Graph / social-preview size. Like the HTML card it uses no
    external fonts/images/scripts (system serif stack, an inline hatch pattern),
    so it renders identically offline and is safe to embed anywhere."""
    e = html.escape
    lab = model["labels"]
    font = "Georgia, 'Songti SC', 'Noto Serif CJK SC', 'Noto Serif', serif"
    mono = "'Courier New', ui-monospace, monospace"
    pct = max(0, min(100, int(model["score_pct"])))
    fill_w = int(1056 * pct / 100)  # gauge track spans x=72..1128 (width 1056)
    # The score sits at the right end of the track: light ink when the dark fill
    # reaches it (high scores), dark ink over the pale unfilled track otherwise.
    score_color = "#fbfbf7" if pct >= 90 else "#1a1a1a"

    # Everything is width-wrapped (no reliance on renderer textLength support, which
    # Quick Look and some rasterizers ignore): the long en center name breaks to two
    # lines, the short zh one stays on one. The vertical rhythm below is computed off
    # the header height so nothing collides with the footer in either language.
    header_lines = _wrap(model["center_name"], budget=21, max_lines=2)
    header_tspans = "".join(
        f'<tspan x="596" dy="{0 if i == 0 else 32}">{e(t)}</tspan>'
        for i, t in enumerate(header_lines)
    )
    hy = (len(header_lines) - 1) * 32
    rule_y = 100 + hy
    meta_y = rule_y + 34
    idx_y = meta_y + 56
    gauge_y = idx_y + 16
    prim_y = gauge_y + 40 + 40

    dx_lines = _wrap(model["dx"], budget=21, max_lines=2)
    dx_y = prim_y + 36
    dx_tspans = "".join(
        f'<tspan x="72" dy="{0 if i == 0 else 34}">{e(t)}</tspan>'
        for i, t in enumerate(dx_lines)
    )
    if model["rx"]:
        rx_label_y = dx_y + (len(dx_lines) - 1) * 34 + 34
        rx_val_y = rx_label_y + 28
        rx_lines = _wrap(model["rx"], budget=28, max_lines=2)
        rx_tspans = "".join(
            f'<tspan x="72" dy="{0 if i == 0 else 26}">{e(t)}</tspan>'
            for i, t in enumerate(rx_lines)
        )
        rx_block = (
            f'<text x="72" y="{rx_label_y}" font-family="{font}" font-size="13" '
            f'letter-spacing="1" fill="#666">{e(lab["rx"].upper())}</text>'
            f'<text x="72" y="{rx_val_y}" font-family="{font}" font-size="19" '
            f'font-style="italic" fill="#1a1a1a">{rx_tspans}</text>'
        )
    else:
        rx_block = ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" \
viewBox="0 0 1200 630" role="img" lang="{e(model.get("lang", "en"))}" \
aria-label="{e(model["center_name"])} — {e(lab["index"])} {e(str(model["score"]))} / 100">
  <defs>
    <pattern id="hatch" width="12" height="12" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <rect width="12" height="12" fill="#2b2b2b"/>
      <rect width="6" height="12" fill="#3a3a3a"/>
    </pattern>
  </defs>
  <rect width="1200" height="630" fill="#ecece4"/>
  <rect x="36" y="36" width="1128" height="558" fill="#cfcfc4"/>
  <rect x="32" y="32" width="1128" height="558" fill="#fbfbf7" stroke="#cfcfc4" stroke-width="1"/>
  <text x="596" y="78" text-anchor="middle" font-family="{font}" font-size="26" \
font-weight="700" fill="#1a1a1a">{header_tspans}</text>
  <line x1="72" y1="{rule_y}" x2="1120" y2="{rule_y}" stroke="#1a1a1a" stroke-width="2"/>
  <text x="72" y="{meta_y}" font-family="{mono}" font-size="16" fill="#555">\
{e(lab["case"])} {e(model["case_no"])}</text>
  <text x="1120" y="{meta_y}" text-anchor="end" font-family="{mono}" font-size="16" fill="#555">\
{e(lab["subject"])}: {e(model["subject"])}</text>
  <text x="72" y="{idx_y}" font-family="{font}" font-size="14" letter-spacing="2" fill="#555">\
{e(lab["index"].upper())}</text>
  <rect x="72" y="{gauge_y}" width="1056" height="40" fill="#e6e6dd" stroke="#b9b9ac" stroke-width="1"/>
  <rect x="72" y="{gauge_y}" width="{fill_w}" height="40" fill="url(#hatch)"/>
  <text x="1112" y="{gauge_y + 28}" text-anchor="end" font-family="{font}" font-size="22" \
font-weight="700" fill="{score_color}">{e(str(model["score"]))} / 100</text>
  <text x="72" y="{prim_y}" font-family="{font}" font-size="13" letter-spacing="1" fill="#666">\
{e(lab["primary"].upper())}</text>
  <text x="72" y="{dx_y}" font-family="{font}" font-size="26" font-weight="700" fill="#1a1a1a">\
{dx_tspans}</text>
  {rx_block}
  <rect x="72" y="524" width="1056" height="20" fill="url(#hatch)"/>
  <text x="596" y="566" text-anchor="middle" font-family="{font}" font-size="14" fill="#555">\
{e(lab["footer"])}</text>
</svg>"""


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
<html lang="{e(model.get("lang", "en"))}"><head><meta charset="utf-8">
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
