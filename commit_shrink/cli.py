"""Command-line entry point: `commit-shrink [PATH]`.

PATH accepts a local filesystem path, or a remote spec (a URL, or
github:owner/repo) to assess a public repository without cloning it
yourself first -- see commit_shrink/remote.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console

from . import history
from .collector import NotARepoError
from .pipeline import SUPPORTED_LANGS, NoCommitsError, assess_repo, load_config
from .remote import (
    CloneError,
    RemoteAuthorRequiredError,
    is_remote_spec,
    local_repo,
    require_author_for_remote,
)
from .report import ReportRenderer
from .waiting import run_with_rotating_messages


def assess(
    path: str = typer.Argument(
        ".", help="Local git repo path, or a remote spec (URL / github:owner/repo)."
    ),
    days: int = typer.Option(7, help="Length of the assessment period in days."),
    until: Optional[str] = typer.Option(
        None, help="End of the assessment period (ISO datetime; defaults to now)."
    ),
    author: Optional[str] = typer.Option(None, help="Filter commits by author (git --author)."),
    lang: str = typer.Option("en", help="Report language: 'en' or 'zh'."),
) -> None:
    """Generate a developer mental-health assessment from the repo's git log."""
    console = Console()
    if lang not in SUPPORTED_LANGS:
        raise typer.BadParameter(
            f"--lang must be one of {', '.join(SUPPORTED_LANGS)}, got {lang!r}"
        )
    cfg = load_config(lang)
    rc = cfg["report_copy"]
    try:
        end = datetime.fromisoformat(until).astimezone() if until else None
    except ValueError:
        raise typer.BadParameter(f"--until must be an ISO datetime, got {until!r}")
    try:
        require_author_for_remote(path, author)
    except RemoteAuthorRequiredError:
        console.print(rc["errors"]["author_required_for_remote"])
        raise typer.Exit(code=2)
    def _work():
        with local_repo(path, days=days, until=end, author=author) as repo_path:
            ctx = history.load_context([repo_path])
            assessment = assess_repo(
                repo_path,
                days=days,
                until=end,
                author=author,
                cfg=cfg,
                techdebt_history=ctx.techdebt_index,
            )
            source = "remote" if is_remote_spec(path) else "local"
            trend = history.finalize(ctx, assessment, [repo_path], source=source)
        return assessment, trend

    messages = rc["loading_messages"]
    try:
        # Cycle the waiting-room lines while the (blocking) clone/analysis runs
        # on a worker thread; any error is re-raised here and handled below.
        with console.status(messages[0]) as status:
            assessment, trend = run_with_rotating_messages(_work, messages, status.update)
    except CloneError as e:
        console.print(rc["errors"]["clone_failed"].format(error=str(e)))
        raise typer.Exit(code=2)
    except NotARepoError:
        console.print(rc["errors"]["not_a_repo"])
        raise typer.Exit(code=2)
    except NoCommitsError:
        console.print(rc["errors"]["no_commits"])
        raise typer.Exit(code=1)
    except RuntimeError as e:
        # Unexpected git failure: show the message, never a raw traceback.
        console.print(str(e))
        raise typer.Exit(code=2)
    ReportRenderer(cfg).render(console, assessment, trend)


def main() -> None:
    typer.run(assess)


if __name__ == "__main__":
    main()
