"""Command-line entry point: `commit-shrink [PATH]`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .collector import NotARepoError
from .pipeline import NoCommitsError, assess_repo, load_config
from .report import ReportRenderer


def assess(
    path: Path = typer.Argument(Path("."), help="Path to the git repository to assess."),
    days: int = typer.Option(7, help="Length of the assessment period in days."),
    until: Optional[str] = typer.Option(
        None, help="End of the assessment period (ISO datetime; defaults to now)."
    ),
    author: Optional[str] = typer.Option(None, help="Filter commits by author (git --author)."),
) -> None:
    """Generate a developer mental-health assessment from the repo's git log."""
    console = Console()
    cfg = load_config()
    try:
        end = datetime.fromisoformat(until).astimezone() if until else None
    except ValueError:
        raise typer.BadParameter(f"--until must be an ISO datetime, got {until!r}")
    try:
        assessment = assess_repo(path, days=days, until=end, author=author, cfg=cfg)
    except NotARepoError:
        console.print(cfg["report_copy"]["errors"]["not_a_repo"])
        raise typer.Exit(code=2)
    except NoCommitsError:
        console.print(cfg["report_copy"]["errors"]["no_commits"])
        raise typer.Exit(code=1)
    except RuntimeError as e:
        # Unexpected git failure: show the message, never a raw traceback.
        console.print(str(e))
        raise typer.Exit(code=2)
    ReportRenderer(cfg).render(console, assessment)


def main() -> None:
    typer.run(assess)


if __name__ == "__main__":
    main()
