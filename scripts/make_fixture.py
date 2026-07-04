"""Build a demonstration repository whose commit history is clinically rich.

The generated history covers every detectable symptom in symptoms.yaml and
doubles as the pytest fixture and the README screenshot material. Timestamps
anchor on the most recent completed Mon-Sun week relative to --end, so
weekday/weekend detection is deterministic.

Usage:
    python scripts/make_fixture.py [--path fixture-repo] [--end ISO_DATETIME]
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

AUTHOR_NAME = "Demo Developer"
AUTHOR_EMAIL = "dev@example.com"


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo: Path, message: str, when: datetime, files: dict[str, str], append: bool = False) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if append and p.exists():
            p.write_text(p.read_text() + content)
        else:
            p.write_text(content)
    _git(repo, "add", "-A")
    iso = when.isoformat()
    env = {**os.environ, "GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso}
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message, "--allow-empty"],
        check=True,
        capture_output=True,
        env=env,
    )


def build_fixture(path: Path, end: datetime | None = None) -> tuple[datetime, datetime]:
    """Create the repo; returns (period_start, period_end) for the CLI run."""
    end = end or datetime.now().astimezone()
    sunday = (end - timedelta(days=(end.weekday() + 1) % 7)).replace(
        hour=23, minute=59, second=0, microsecond=0
    )
    if sunday > end:
        sunday -= timedelta(days=7)
    monday = (sunday - timedelta(days=6)).replace(hour=0, minute=0)

    def at(day_offset: int, hour: int, minute: int) -> datetime:
        return (monday + timedelta(days=day_offset)).replace(hour=hour, minute=minute)

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.name", AUTHOR_NAME)
    _git(path, "config", "user.email", AUTHOR_EMAIL)
    # Serve partial (blobless) clones over file://, as GitHub does, so tests
    # exercise the same clone path remote.local_repo uses in production.
    _git(path, "config", "uploadpack.allowFilter", "true")

    # Bootstrap far before the period: gives the binge detector its silence gap.
    _commit(path, "chore: bootstrap project", at(-5, 9, 0), {"README.md": "# demo\n"})

    # Monday: binge after >=72h of silence, described as 'update' (GIT-36.6 IV).
    _commit(path, "update", at(0, 9, 0), {f"src/module_{i:02d}.py": f"VALUE_{i} = {i}\n" for i in range(25)})
    _commit(path, "feat: initial parser implementation", at(0, 10, 0), {"src/parser.py": "def parse():\n    return None\n"})
    # Negative controls: plain 'why' and a word containing 'fix'.
    _commit(path, "docs: document why we retry on timeout", at(0, 11, 30), {"docs/notes.md": "retry rationale\n"})
    _commit(path, "feat: add prefix handling", at(0, 14, 0), {"src/parser.py": "PREFIX = '#'\n"}, append=True)
    _commit(path, "feat: add config loader", at(1, 14, 0), {"src/config.py": "CONFIG = {}\n"})

    # Tuesday evening: anxious burst #1, all low-information (GIT-47.1 + GIT-11.2).
    for i, msg in enumerate(["test", "test", ".", "tmp", "update", "asdf"]):
        _commit(path, msg, at(1, 20, i * 5), {"scratch.txt": f"{i}\n"}, append=True)

    # Wednesday: WIP chain (GIT-50.0).
    for i, msg in enumerate(["wip", "wip: auth flow", "WIP"]):
        _commit(path, msg, at(2, 11, i * 20), {"src/auth.py": f"# step {i}\n"}, append=True)

    # Thursday small hours: the canonical fix chain (GIT-42.2 grade IV).
    chain = [
        ("fix login bug", 2, 14),
        ("fix login bug again", 2, 31),
        ("really fix login bug", 2, 58),
        ("PLEASE WORK", 3, 22),
        ("ok it was a typo", 3, 52),
    ]
    for msg, h, m in chain:
        _commit(path, msg, at(3, h, m), {"src/login.py": f"# {msg}\n"}, append=True)
    _commit(path, "wtf why is the cache stale", at(3, 3, 55), {"src/cache.py": "TTL = 60\n"})

    # Thursday late evening: anxious burst #2 (second episode confirms GIT-47.1).
    for i, msg in enumerate([".", "1", "misc", "stuff", "temp"]):
        _commit(path, msg, at(3, 22, i * 5), {"scratch.txt": f"b{i}\n"}, append=True)

    # Friday: Chinese-language fix with an outburst, at night (lexicon patch path).
    _commit(path, "修复缓存又崩了 卧槽", at(4, 1, 0), {"src/cache.py": "TTL = 30\n"}, append=True)
    # Tech debt attachment (GIT-77.7).
    _commit(path, "temporary workaround for session bug, will fix properly later", at(4, 15, 0), {"src/session.py": "HACK = True\n"})
    # Regret, then second-order regret on Saturday (GIT-31.0 grade IV).
    _commit(path, 'Revert "feat: add config loader"\n\nThis reverts commit 0000000000000000000000000000000000000000.', at(4, 15, 30), {"src/config.py": "# reverted\n"})
    _commit(path, 'Revert "Revert \\"feat: add config loader\\""', at(5, 10, 0), {"src/config.py": "CONFIG = {}\n"})

    # Saturday afternoon: naming collapse (GIT-60.1).
    finals = [
        ("report final", 15, 3),
        ("report final v2", 15, 47),
        ("report final v2 REAL", 16, 22),
        ("report final v2 REAL (use this one)", 16, 41),
    ]
    for msg, h, m in finals:
        _commit(path, msg, at(5, h, m), {"report.md": msg + "\n"}, append=True)

    # Saturday night: a 'quick fix' whose follow-ups betray it (GIT-13.0 grade IV).
    _commit(path, "quick fix for date parsing", at(5, 23, 50), {"src/dateparse.py": "FMT = '%Y'\n"})
    _commit(path, "fix date parsing again", at(6, 0, 30), {"src/dateparse.py": "FMT = '%Y-%m'\n"}, append=True)
    _commit(path, "fix tz handling in date parsing, should work now", at(6, 1, 0), {"src/dateparse.py": "TZ = True\n"}, append=True)

    # Sunday small hours: P0 incident with magical thinking (GIT-99.0 + GIT-70.7 IV).
    _commit(path, "hotfix: prod down. this should work. please.", at(6, 4, 47), {"src/login.py": "PATCHED = True\n"}, append=True)

    return monday, sunday


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("fixture-repo"))
    parser.add_argument("--end", type=str, default=None, help="ISO datetime anchor (default: now)")
    args = parser.parse_args()
    end = datetime.fromisoformat(args.end).astimezone() if args.end else None
    start, finish = build_fixture(args.path, end)
    print(f"fixture repo: {args.path}")
    print(f"period: {start.isoformat()} .. {finish.isoformat()}")
    print(f"suggested run: commit-shrink {args.path} --days 7 --until {finish.isoformat()}")


if __name__ == "__main__":
    main()
