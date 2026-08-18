"""The event loop each process runs on, which decides whether it can reach the database.

These are the only tests here that assert something about psycopg without a database, and
they can, because the fault they guard against happens before any socket opens: psycopg
inspects the running loop, refuses the proactor one, and raises. So an attempt to connect
somewhere that certainly is not listening tells the two cases apart. Refused by the loop
gives one error; allowed by the loop and then refused by the network gives another, and it
is the second that says the loop is usable.

The refusal is a psycopg restriction rather than a law, and if a later version lifts it,
the Windows-only test below starts failing. That is the intended signal: it means this
module can be deleted, not that something broke.

Both loops are named explicitly here. The suite settles its own default to one the
application can use, so a test that took whatever it was given would prove nothing about
either.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.runtime import (
    explain_unusable_loop,
    loop_factory,
    running_loop_reaches_postgres,
)

#: Nothing listens on port 1, and no name has to be resolved to find that out, so the
#: attempt fails locally and immediately rather than depending on the network.
_NOWHERE = "postgresql://u:p@127.0.0.1:1/db"

_REFUSED_BY_THE_LOOP = "ProactorEventLoop"


async def _attempt_a_connection() -> None:
    import psycopg

    await psycopg.AsyncConnection.connect(_NOWHERE, connect_timeout=2)


def _error_from(**run_kwargs: object) -> str:
    try:
        asyncio.run(_attempt_a_connection(), **run_kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    raise AssertionError("something answered on a port nothing should be listening on")


class TestTheChosenLoop:
    def test_psycopg_gets_as_far_as_the_network(self) -> None:
        """The whole point. On the loop this module picks, a connection attempt fails
        because nothing is listening — which is a real answer about the network, and the
        only kind of failure the caller should ever have to interpret."""
        error = _error_from(loop_factory=loop_factory())
        assert _REFUSED_BY_THE_LOOP not in error

    def test_windows_is_given_a_selector_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        assert loop_factory() is asyncio.SelectorEventLoop

    def test_everywhere_else_keeps_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`None` is what `asyncio.run` already means by "decide for me", so the call
        site reads the same on every platform."""
        monkeypatch.setattr(sys, "platform", "linux")
        assert loop_factory() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the loop is only refused on Windows")
class TestTheLoopThatDoesNotWork:
    def test_the_proactor_loop_is_refused_before_any_connection(self) -> None:
        """Why this module exists. Left as a tripwire: should a later psycopg accept the
        proactor loop, this fails, and the answer is to delete the workaround.

        The loop is named rather than left to the default, because the suite settles that
        default to a working one — so relying on it here would test nothing.
        """
        assert _REFUSED_BY_THE_LOOP in _error_from(loop_factory=asyncio.ProactorEventLoop)

    def test_a_process_on_it_is_told_it_cannot_reach_postgres(self) -> None:
        async def check() -> bool:
            return running_loop_reaches_postgres()

        assert asyncio.run(check(), loop_factory=asyncio.ProactorEventLoop) is False

    def test_a_process_on_the_chosen_loop_is_told_it_can(self) -> None:
        async def check() -> bool:
            return running_loop_reaches_postgres()

        assert asyncio.run(check(), loop_factory=loop_factory()) is True


class TestTheExplanation:
    def test_it_names_the_loop_and_what_to_do(self) -> None:
        """The message replaces one that arrives a query later and explains only itself,
        so it has to carry both halves: which loop, and how to get a different one."""
        message = explain_unusable_loop()
        assert _REFUSED_BY_THE_LOOP in message
        assert "--reload" in message

    def test_it_says_the_failure_precedes_the_network(self) -> None:
        """Without this the reader goes looking at connectivity, which is the expensive
        mistake and the one already made once here."""
        assert "before it reaches the network" in explain_unusable_loop()
