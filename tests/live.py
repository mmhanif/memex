"""A real uvicorn server on a loopback socket, for SSE and browser tests."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import uvicorn

from memex.launcher.net import bind_loopback
from memex.web.app import AppState, create_app


@contextmanager
def live_server(make_state: Callable[[int], AppState]) -> Iterator[AppState]:
    """Serve `make_state(port)` with the watcher on until the block ends."""
    sock = bind_loopback(0)
    state = make_state(sock.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(state),
            log_level="warning",
            lifespan="on",
            access_log=False,
            timeout_graceful_shutdown=1,  # open event streams never end on their own
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("the live server didn't start")
        time.sleep(0.02)
    try:
        yield state
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
