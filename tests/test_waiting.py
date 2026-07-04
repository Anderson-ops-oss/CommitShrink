"""Unit tests for the rotating-wait helper (commit_shrink.waiting).

The animation itself isn't tested; what matters is that the work still runs on
the worker thread, its return value comes back, and -- critically -- an
exception it raises is re-raised on the calling thread so a caller's error
handling (CloneError / NoCommitsError / ...) behaves exactly as before.
"""

from __future__ import annotations

import threading
import time

import pytest

from commit_shrink.waiting import run_with_rotating_messages

MESSAGES = ["a", "b", "c", "d"]


def test_returns_work_result():
    shown: list[str] = []
    result = run_with_rotating_messages(lambda: 42, MESSAGES, shown.append)
    assert result == 42
    assert shown  # at least the first message was shown
    assert set(shown) <= set(MESSAGES)


def test_reraises_work_exception_on_calling_thread():
    class Boom(Exception):
        pass

    def work():
        raise Boom("from the worker")

    with pytest.raises(Boom, match="from the worker"):
        run_with_rotating_messages(work, MESSAGES, lambda _m: None)


def test_rotates_while_work_is_slow():
    shown: list[str] = []

    def slow():
        time.sleep(0.06)
        return "done"

    result = run_with_rotating_messages(slow, MESSAGES, shown.append, interval=0.01)
    assert result == "done"
    assert len(shown) > 1  # rotated at least once beyond the first message


def test_fast_work_shows_only_the_first_message():
    shown: list[str] = []
    run_with_rotating_messages(lambda: None, MESSAGES, shown.append, interval=10)
    assert len(shown) == 1  # finished within the first interval; never rotated


def test_prepare_thread_hook_receives_the_worker_thread():
    seen: list[threading.Thread] = []
    run_with_rotating_messages(
        lambda: None,
        MESSAGES,
        lambda _m: None,
        prepare_thread=seen.append,
    )
    assert len(seen) == 1 and isinstance(seen[0], threading.Thread)


def test_empty_messages_do_not_crash():
    result = run_with_rotating_messages(lambda: "ok", [], lambda _m: None)
    assert result == "ok"


def test_source_message_list_is_not_mutated():
    original = list(MESSAGES)
    run_with_rotating_messages(lambda: None, MESSAGES, lambda _m: None)
    assert MESSAGES == original  # shuffled a copy, not the caller's list
