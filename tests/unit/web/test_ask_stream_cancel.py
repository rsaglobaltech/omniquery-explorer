"""Cancellation semantics of /ask/stream.

We exercise the producer directly (bypassing FastAPI) so the test stays
fast and deterministic. The producer is an async generator that:
- yields ``event: started`` immediately,
- launches the EDA pipeline as a child task,
- on CancelledError, cancels the child and re-raises.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from omniquery.adapters.web import app as web_app
from omniquery.adapters.web.schemas import AskRequest


class _SlowGraph:
    """Graph stub whose ``run`` awaits forever unless cancelled."""

    def __init__(self) -> None:
        self.cancel_observed = False

    async def run(self, **kwargs: Any) -> Any:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancel_observed = True
            raise


@pytest.mark.asyncio
async def test_producer_cancels_child_on_client_disconnect():
    slow = _SlowGraph()

    class _StubContainer:
        def eda_session_graph(self, _url: str):
            return slow

    with patch.object(web_app, "get_container", return_value=_StubContainer()):
        req = AskRequest(
            question="q", connection_url="postgres://u:p@h/d", max_rows=10
        )
        response = await web_app.ask_stream(req)
        agen = response.body_iterator

        # First chunk is the synchronous 'started' event.
        first = await agen.__anext__()
        assert "started" in first

        # Simulate client disconnect: the FastAPI runtime cancels the
        # task waiting for the next chunk. Give the producer a few ticks
        # to enter ``await task`` before we cancel, then assert that the
        # cancellation propagates back out (the handler re-raises after
        # cleaning up the child).
        next_task = asyncio.ensure_future(agen.__anext__())
        for _ in range(10):
            await asyncio.sleep(0)
        next_task.cancel()
        with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
            await next_task

    # The graph task must have observed the cancellation propagated by
    # our handler — proving DB / LLM clean-up happened.
    assert slow.cancel_observed is True
