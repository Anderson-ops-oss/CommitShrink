"""Regenerate the golden-sample report body in docs/report-sample.md.

The golden sample is the assessment of the deterministic demo repository built
by scripts/make_fixture.py, rendered to Chinese Markdown. Anchoring the fixture
to a fixed end date (and normalizing the one volatile line, the generation
timestamp) makes the output byte-reproducible, so docs/report-sample.md is a
real snapshot of tool output rather than a hand-authored aspiration.

    python scripts/make_golden_sample.py           # rewrite the golden region
    python scripts/make_golden_sample.py --check    # exit 1 if it would change

tests/test_golden_sample.py imports render_golden_body() and asserts the doc's
golden region still matches a fresh render, so drift breaks CI.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOC = REPO_ROOT / "docs" / "report-sample.md"

# Fixed anchor: 2026-06-28 is a Sunday, so the assessment week is Mon 06-22 ..
# Sun 06-28 (ISO week 26) -- the same week the golden sample has always used.
GOLDEN_END = datetime.fromisoformat("2026-06-28T23:59:00+00:00")
# The one non-deterministic line (system clock at render time) is pinned to a
# fixed, plausible value so the snapshot is stable.
FROZEN_REPORT_DATE = "2026-06-29 09:00（系统自动生成，无主试效应）"

MARKER_START = "<!-- COMMITSHRINK:GOLDEN:START -->"
MARKER_END = "<!-- COMMITSHRINK:GOLDEN:END -->"
_MARKER_RE = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)
_REPORT_DATE_RE = re.compile(r"(\| 报告日期 \|).*?(\|)")


def _load_fixture_builder():
    spec = importlib.util.spec_from_file_location(
        "make_fixture", REPO_ROOT / "scripts" / "make_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_fixture"] = module
    spec.loader.exec_module(module)
    return module


def render_golden_body() -> str:
    """Render the demo fixture to Chinese Markdown, deterministically."""
    from commit_shrink.pipeline import assess_repo, load_config
    from commit_shrink.report_markdown import render_report_markdown

    builder = _load_fixture_builder()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "demo-repo"
        _start, period_end = builder.build_fixture(repo, end=GOLDEN_END)
        assessment = assess_repo(repo, days=7, until=period_end)
        cfg = load_config("zh")
        md = render_report_markdown(assessment, cfg, None)
    md = _REPORT_DATE_RE.sub(rf"\1 {FROZEN_REPORT_DATE} \2", md)
    return md.strip()


def build_golden_region() -> str:
    return f"{MARKER_START}\n\n{render_golden_body()}\n\n{MARKER_END}"


def splice(check_only: bool = False) -> bool:
    original = GOLDEN_DOC.read_text(encoding="utf-8")
    if MARKER_START not in original or MARKER_END not in original:
        raise RuntimeError(f"{GOLDEN_DOC} is missing the {MARKER_START} / {MARKER_END} markers")
    updated = _MARKER_RE.sub(build_golden_region(), original, count=1)
    changed = updated != original
    if changed and not check_only:
        GOLDEN_DOC.write_text(updated, encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the doc would change")
    args = parser.parse_args()
    changed = splice(check_only=args.check)
    if args.check and changed:
        print("docs/report-sample.md golden region is stale; run scripts/make_golden_sample.py")
        raise SystemExit(1)
    print("golden region updated" if changed else "golden region already up to date")


if __name__ == "__main__":
    main()
