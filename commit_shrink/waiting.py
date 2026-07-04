"""Rotate playful "please wait" messages while a blocking task runs.

The assessment pipeline (clone -> git log -> diagnosis) is synchronous and can
take a few seconds -- especially a remote clone. A single thread stuck inside
subprocess.run() can't also animate text, so this runs the work on a background
thread and cycles status messages on the calling thread until it finishes --
the same trick a chat CLI uses for its "thinking..." line.

UI-agnostic on purpose: the caller supplies a ``show(text)`` callback (Rich's
``status.update``, a Streamlit placeholder, ...), so this module depends on
neither Rich nor Streamlit. Messages are shuffled per run (the order varies
each time), the first is shown immediately (no blank gap), and the loop exits
the instant the work is done rather than padding to a fixed schedule.

Any exception the work raises is re-raised here on the calling thread, so a
caller's surrounding try/except behaves exactly as if the work had run inline.
"""

from __future__ import annotations

import itertools
import random
import threading
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")

ROTATE_INTERVAL_SECONDS = 2.5


def run_with_rotating_messages(
    work: Callable[[], T],
    messages: Sequence[str],
    show: Callable[[str], object],
    *,
    interval: float = ROTATE_INTERVAL_SECONDS,
    prepare_thread: Callable[[threading.Thread], object] | None = None,
) -> T:
    """Run ``work()`` on a worker thread, cycling ``messages`` through ``show``.

    Returns ``work()``'s value; re-raises its exception on the calling thread.
    ``prepare_thread``, if given, is called with the worker thread before it is
    started -- Streamlit uses it to attach its ScriptRunContext so the thread
    doesn't trip a "missing ScriptRunContext" warning.
    """
    outcome: dict[str, object] = {}

    def _runner() -> None:
        try:
            outcome["value"] = work()
        except BaseException as exc:  # re-raised on the calling thread below
            outcome["error"] = exc

    worker = threading.Thread(target=_runner, daemon=True)
    if prepare_thread is not None:
        prepare_thread(worker)

    # Shuffle a defensive copy so the source list (the yaml config) is untouched
    # and the order differs run to run; fall back to a blank tick if empty.
    order = [m for m in messages if m] or [""]
    random.shuffle(order)
    ticker = itertools.cycle(order)

    worker.start()
    show(next(ticker))
    while True:
        worker.join(timeout=interval)
        if not worker.is_alive():
            break
        show(next(ticker))

    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome.get("value")  # type: ignore[return-value]
