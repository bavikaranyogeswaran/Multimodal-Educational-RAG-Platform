"""Which event loop a process must run on to be able to reach the database.

The database is reached through psycopg's async interface, and psycopg refuses to run on
the proactor loop Windows uses by default. It refuses immediately, before opening any
socket, so the failure looks nothing like a database problem: it arrives instantly and
identically whether the database is reachable, unreachable, or does not exist. Reading it
as a connectivity fault and going looking at the network is the obvious mistake, and it
costs an afternoon.

The selector loop has no such restriction. Nothing else in this application depends on
which of the two it gets — the proactor loop exists for named pipes and subprocess
support, neither of which is used here — so choosing the selector loop on Windows costs
nothing and removes the fault.

Every process that starts its own loop has to say so, because there is no global setting
that reaches all of them. `asyncio.run` accepts a factory directly, which is what the
worker and the scripts use. Uvicorn passes its own factory and therefore ignores any
policy set around it, so the API cannot choose from inside itself and checks instead that
whoever started it chose correctly.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

#: What the proactor loop is called when psycopg names it in the error it raises. Kept
#: here so the check and the explanation of the check cannot drift apart.
_REFUSED_LOOP = "ProactorEventLoop"


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """The loop this process should run on, or `None` to accept the default.

    Pass it straight to `asyncio.run`, which treats `None` as "decide for me" — so the
    call reads the same on every platform and only Windows is actually steered.
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None


def running_loop_reaches_postgres() -> bool:
    """Whether the loop already running underneath will let psycopg connect.

    For processes that did not start their own loop and cannot choose one, which in
    practice means anything hosted by a server that starts the loop itself.

    Asks for the running loop specifically, so calling this with no loop raises rather
    than answering about one built on the spot — which would be a loop nothing is going
    to use, and on this machine would answer yes regardless.
    """
    if sys.platform != "win32":
        return True
    return type(asyncio.get_running_loop()).__name__ != _REFUSED_LOOP


def explain_unusable_loop() -> str:
    """Why the current loop will not work, and what to do about it.

    Written out in full because the alternative message is psycopg's, which arrives on
    the first query rather than at startup and says nothing about how the loop was
    chosen or who chose it.
    """
    return (
        f"this process is running on the {_REFUSED_LOOP}, which psycopg refuses to use "
        "for async connections, so every database call will fail before it reaches the "
        "network. Uvicorn selects that loop on Windows unless it is running with a "
        "subprocess, which --reload and --workers both are. Start the server with "
        "--reload for development, or host it on a selector loop."
    )
