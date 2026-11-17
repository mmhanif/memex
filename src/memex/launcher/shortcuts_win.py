"""`memex shortcuts`: a per-user Start-menu shortcut, made with pywin32 (SPEC §13.5)."""

import os
import sys
from pathlib import Path

NAME = "Memex.lnk"


def shortcut_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / NAME


def create_shortcut() -> Path:
    """Point at the `memex.exe` beside this Python (pipx's venv), else `python -m memex`."""
    assert sys.platform == "win32"
    import pythoncom
    from win32com.shell import shell

    exe = Path(sys.executable).with_name("memex.exe")
    target, arguments = (exe, "") if exe.is_file() else (Path(sys.executable), "-m memex")
    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
    )
    link.SetPath(str(target))
    link.SetArguments(arguments)
    link.SetWorkingDirectory(str(Path.home()))
    link.SetDescription("Memex")
    path = shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)
    return path


def remove_shortcut() -> Path:
    path = shortcut_path()
    path.unlink(missing_ok=True)
    return path
