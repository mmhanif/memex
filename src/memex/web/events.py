"""`GET /api/events`: the `changed` event stream (SPEC §5.6).

The client reads it with `fetch`, because `EventSource` can't send `X-Memex` (§12).
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from memex.core.watch import Change
from memex.web.state import AppState, app_state

router = APIRouter(prefix="/api")

KEEPALIVE_S = 15.0


@router.get("/events")
async def events(state: Annotated[AppState, Depends(app_state)]) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[list[Change]] = asyncio.Queue()

    def listener(changes: list[Change]) -> None:  # runs on the watcher thread
        loop.call_soon_threadsafe(queue.put_nowait, changes)

    unsubscribe = state.feed.subscribe(listener)

    async def stream() -> AsyncIterator[str]:
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    changes = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                data = {"changes": [{"path": c.path, "hash": c.hash} for c in changes]}
                yield f"event: changed\ndata: {json.dumps(data)}\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )
