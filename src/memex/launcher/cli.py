"""`memex`: the console launcher (SPEC §13.3-§13.5).

memex [--workspace PATH] [--port N] [--no-browser]
memex shortcuts [--remove]
memex --version
"""

import argparse
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from memex import version
from memex.core.config import load_app_config, locate_workspace, memex_home
from memex.launcher import handoff
from memex.launcher.logs import configure_logging
from memex.launcher.net import HOST, PORT_ATTEMPTS, AllPortsBusy, bind_first_free, bind_loopback
from memex.launcher.runfile import RunInfo, read_run_file, remove_run_file, write_run_file
from memex.web.app import AppState, create_app

log = logging.getLogger("memex.launcher")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "shortcuts":
        return _shortcuts(remove=args.remove)
    home = memex_home()
    configure_logging(home)
    workspace = Path(os.path.abspath(args.workspace.expanduser())) if args.workspace else None
    port = args.port or load_app_config(home).port
    try:
        sock = bind_loopback(port)
    except OSError:
        handed_off = _hand_off(home, port, workspace, open_browser=not args.no_browser)
        if handed_off is not None:
            return handed_off
        try:
            sock, bound = bind_first_free(port)
        except AllPortsBusy as e:
            print(f"Can't start Memex: {e}", file=sys.stderr)
            return 1
        if bound != port:
            log.warning(
                "Port %d is in use by another program, so Memex is on port %d this time. "
                "Browser bookmarks to Memex won't work this session.",
                port,
                bound,
            )
    return _serve(sock, home, workspace, open_browser=not args.no_browser)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memex", description="Run Memex.")
    parser.add_argument("--version", action="version", version=f"memex {version()}")
    parser.add_argument("--workspace", type=Path, help="the Workspace folder (remembered)")
    parser.add_argument("--port", type=_port, help="the port to listen on (default 47615)")
    parser.add_argument("--no-browser", action="store_true", help="print the link, don't open it")
    commands = parser.add_subparsers(dest="command")
    shortcuts = commands.add_parser("shortcuts", help="add a Start-menu shortcut (Windows)")
    shortcuts.add_argument("--remove", action="store_true", help="remove it instead")
    return parser


def _port(text: str) -> int:
    port = int(text)
    if not 0 < port < 65536:
        raise argparse.ArgumentTypeError("a port is a number from 1 to 65535")
    return port


def _hand_off(home: Path, port: int, workspace: Path | None, *, open_browser: bool) -> int | None:
    """If a verified Memex holds the port, open it (or refuse) and return the exit code.

    None means the listener is a stranger, so the caller falls back to the next port.
    """
    info = read_run_file(home)
    # The recorded instance may itself have fallen back from this port (§13.3); one on
    # any other port isn't the Memex holding ours.
    if info is None or not port <= info.port < port + PORT_ATTEMPTS:
        return None
    running = handoff.verify(info)
    if running is None:
        return None
    if workspace is not None and (
        running.workspace is None or not handoff.same_workspace(running.workspace, workspace)
    ):
        where = running.workspace or "another Workspace (waiting for Setup)"
        print(f"Memex is already running on {where}. Quit it first to switch", file=sys.stderr)
        return 1
    code = handoff.request_code(info)
    if code is None:
        print("Memex is already running but didn't answer. Quit it and try again", file=sys.stderr)
        return 1
    url = _auth_url(running.port, code)
    print(url)
    if open_browser and _open(url):
        print("Memex is already running; opened it in your browser")
    else:
        print("Memex is already running; open the link above in your browser")
    return 0


def _serve(sock: socket.socket, home: Path, workspace: Path | None, *, open_browser: bool) -> int:
    port = sock.getsockname()[1]
    location = locate_workspace(workspace, home)
    state = AppState.from_location(location, port=port, home=home)
    key = secrets.token_bytes(32)
    state.launcher_key = key
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(state),
            log_config=None,  # ours, from configure_logging
            access_log=False,  # request lines can carry the one-time code
            lifespan="on",
            timeout_graceful_shutdown=1,  # open event streams never end on their own
        )
    )
    state.on_quit = lambda: setattr(server, "should_exit", True)
    root = state.workspace.root if state.workspace is not None else None
    write_run_file(home, RunInfo(os.getpid(), port, str(root) if root else None, key))
    threading.Thread(
        target=_announce, args=(server, state, open_browser), name="memex-announce", daemon=True
    ).start()
    log.info("Memex %s starting on %s:%d", version(), HOST, port)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        remove_run_file(home, key)
        sock.close()
    log.info("Memex stopped")
    return 0


def _announce(server: uvicorn.Server, state: AppState, open_browser: bool) -> None:
    """Once the server is listening: print the link (never logged) and open the browser."""
    while not server.started:
        if server.should_exit:
            return
        time.sleep(0.05)
    if state.workspace is not None:
        print(f"Workspace: {state.workspace.root}")
    else:
        print("No Workspace yet: the link opens Setup")
    url = _auth_url(state.port, state.session.issue_code())
    print(f"Memex is running. Open it with this link (it works once):\n{url}")
    print("Close this window or press Ctrl-C to stop Memex.")
    if open_browser:
        _open(url)


def _auth_url(port: int, code: str) -> str:
    return f"http://{HOST}:{port}/auth?code={code}"


def _open(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def _shortcuts(*, remove: bool) -> int:
    if sys.platform != "win32":
        print("Shortcuts are only made on Windows for now", file=sys.stderr)
        return 1
    from memex.launcher import shortcuts_win

    path = shortcuts_win.remove_shortcut() if remove else shortcuts_win.create_shortcut()
    print(f"{'Removed' if remove else 'Added'} {path}")
    return 0
