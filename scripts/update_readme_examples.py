"""Regenerate the "live" sample report embedded in README.md / README.zh-CN.md
from this repo's own git log.

Run on a schedule by .github/workflows/update-readme-example.yml; also
runnable locally to preview a change before it lands:

    python scripts/update_readme_examples.py

COMMIT_SHRINK_CACHE_DIR is pointed at a repo-local directory (unless already
set) so week-over-week trend history survives across stateless CI runs, as
long as that directory is committed alongside the README -- see
history.py::_cache_dir.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("COMMIT_SHRINK_CACHE_DIR", str(REPO_ROOT / ".commit-shrink-cache"))

from commit_shrink.pipeline import NoCommitsError, load_config
from commit_shrink.report_markdown import render_report_markdown
from commit_shrink.run import run_assessment

ASSESSMENT_DAYS = 7

MARKER_START = "<!-- COMMITSHRINK:LIVE-EXAMPLE:START -->"
MARKER_END = "<!-- COMMITSHRINK:LIVE-EXAMPLE:END -->"
_MARKER_RE = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)

_LAST_UPDATED_NOTE = {
    "en": "_Regenerated automatically from this repo's own commits — last updated {stamp}._",
    "zh": "_本节由本仓库自身的提交历史自动生成 — 最近更新于 {stamp}。_",
}

TARGETS = [
    ("en", REPO_ROOT / "README.md"),
    ("zh", REPO_ROOT / "README.zh-CN.md"),
]


def _render(lang: str) -> str:
    cfg = load_config(lang)
    result = run_assessment(str(REPO_ROOT), days=ASSESSMENT_DAYS, until=None, author=None, cfg=cfg)
    body = render_report_markdown(result.assessment, cfg, result.trend).rstrip("\n")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = _LAST_UPDATED_NOTE[lang].format(stamp=stamp)
    return f"{MARKER_START}\n\n{note}\n\n{body}\n\n{MARKER_END}"


def _splice(path: Path, replacement: str) -> bool:
    original = path.read_text(encoding="utf-8")
    if MARKER_START not in original or MARKER_END not in original:
        raise RuntimeError(f"{path} is missing the {MARKER_START} / {MARKER_END} markers")
    updated = _MARKER_RE.sub(replacement, original, count=1)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    changed = []
    for lang, path in TARGETS:
        try:
            replacement = _render(lang)
        except NoCommitsError:
            print(f"{lang}: no commits in the last {ASSESSMENT_DAYS} days -- leaving {path.name} untouched")
            continue
        if _splice(path, replacement):
            changed.append(path.name)
    print("changed: " + ", ".join(changed) if changed else "no changes")


if __name__ == "__main__":
    main()
