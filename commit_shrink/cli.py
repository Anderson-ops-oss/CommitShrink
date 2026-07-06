"""Command-line entry point: `commit-shrink [PATH]`.

PATH accepts a local filesystem path; a remote spec (a URL, or
github:owner/repo) to assess a public repository without cloning it
yourself first; or gh-user:owner to assess all of a user's public repos as
one merged timeline -- see commit_shrink/remote.py and commit_shrink/run.py.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from .card import build_card_model, render_card_html
from .collector import NotARepoError
from .github_api import GitHubAPIError
from .pipeline import SUPPORTED_LANGS, NoCommitsError, load_config
from .remote import RemoteAuthorRequiredError, require_author_for_remote
from .remote import CloneError
from .report import ReportRenderer
from .report_markdown import render_report_markdown
from .run import NoReposError, TokenRequiredError, run_assessment
from .waiting import run_with_rotating_messages


def assess(
    path: str = typer.Argument(
        ".",
        help="Local path, a remote spec (URL / github:owner/repo), gh-user:owner for a "
        "user's public repos, or gh-user:@me for your own public + private "
        "(needs GITHUB_TOKEN), assessed as one merged timeline.",
    ),
    days: int = typer.Option(7, help="Length of the assessment period in days."),
    until: Optional[str] = typer.Option(
        None, help="End of the assessment period (ISO datetime; defaults to now)."
    ),
    author: Optional[str] = typer.Option(None, help="Filter commits by author (git --author)."),
    lang: str = typer.Option("en", help="Report language: 'en' or 'zh'."),
    card: Optional[str] = typer.Option(
        None, "--card", help="Also write a shareable HTML summary card to this path."
    ),
    markdown: Optional[str] = typer.Option(
        None, "--markdown", help="Also write the full report as GitHub-Flavored Markdown to this path."
    ),
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
        return run_assessment(path, days=days, until=end, author=author, cfg=cfg)

    messages = rc["loading_messages"]
    try:
        # Cycle the waiting-room lines while the (blocking) clone/analysis runs
        # on a worker thread; any error is re-raised here and handled below.
        with console.status(messages[0]) as status:
            result = run_with_rotating_messages(_work, messages, status.update)
    except CloneError as e:
        console.print(rc["errors"]["clone_failed"].format(error=str(e)))
        raise typer.Exit(code=2)
    except GitHubAPIError as e:
        console.print(rc["errors"]["user_lookup_failed"].format(error=str(e)))
        raise typer.Exit(code=2)
    except TokenRequiredError:
        console.print(rc["errors"]["token_required"])
        raise typer.Exit(code=2)
    except NoReposError as e:
        console.print(rc["errors"]["no_owned_repos" if e.is_self else "no_public_repos"])
        raise typer.Exit(code=1)
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
    renderer = ReportRenderer(cfg)
    renderer.render(console, result.assessment, result.trend)
    if result.discovered_count is not None:
        console.print(rc["aggregate_note_fmt"].format(n=result.repo_count))
    if card:
        Path(card).write_text(
            render_card_html(build_card_model(result.assessment, renderer)), encoding="utf-8"
        )
        console.print(rc["card"]["saved_fmt"].format(path=card))
    if markdown:
        Path(markdown).write_text(
            render_report_markdown(result.assessment, cfg, result.trend), encoding="utf-8"
        )
        console.print(rc["markdown_saved_fmt"].format(path=markdown))


def _ensure_utf8_output() -> None:
    """Force UTF-8 on a redirected/piped stdout+stderr.

    When output is not a terminal, Python encodes it with the locale codepage
    (cp1252 on a typical Windows box), which cannot represent the report's
    Unicode -- the Rich status spinner (Braille), box-drawing, "≥", or CJK
    commit evidence -- and raises UnicodeEncodeError mid-render. A real
    terminal is left untouched (Rich handles its own console); errors="replace"
    is a last-resort guard so output degrades rather than crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        try:
            if reconfigure is not None and not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> None:
    _ensure_utf8_output()
    typer.run(assess)


if __name__ == "__main__":
    main()
