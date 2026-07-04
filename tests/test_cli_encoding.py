"""Regression: the CLI must not crash when stdout is redirected/piped to a
non-UTF-8 sink -- the Windows cp1252 default -- which used to raise
UnicodeEncodeError mid-render (the Rich status spinner's Braille glyphs, the
section rules / metrics table box-drawing, "≥", and CJK commit evidence are all
outside cp1252).

Reproduced deterministically on any platform by forcing PYTHONIOENCODING=cp1252
on a piped subprocess (a pipe reports isatty()==False, exactly like a real file
redirect or CI capture); cli._ensure_utf8_output then reconfigures the stream to
UTF-8 so the render survives.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _has_cp1252_unencodable(text: str) -> bool:
    for ch in text:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            return True
    return False


def test_cli_survives_non_utf8_redirected_stdout(fixture_repo):
    repo, _start, period_end = fixture_repo
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [
            sys.executable, "-m", "commit_shrink.cli", str(repo),
            "--days", "7", "--until", period_end.isoformat(), "--lang", "en",
        ],
        capture_output=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    text = result.stdout.decode("utf-8")
    # Self-check: the report must actually contain a glyph cp1252 can't encode
    # (Rich's box-drawing rules/table), or this test would pass vacuously even
    # without the reconfigure. Surviving + emitting it proves the fix took.
    assert _has_cp1252_unencodable(text), "report emitted no cp1252-hostile glyph"
