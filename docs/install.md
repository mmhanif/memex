# Installing Memex

Memex installs per user, with no admin rights, from the internal package mirror (pip is already set up for it). See [SPEC.md §13](../SPEC.md#13-distribution-and-launch).

## Install

```
py -m pip install --user pipx
pipx ensurepath
pipx install memex
```

Open a new console, then run `memex`. It opens Memex in your browser and prints the link too. Close the console or press Ctrl-C to stop it, or use **Quit Memex** from Ctrl-K.

Optional: `memex shortcuts` adds Memex to the Start menu (`memex shortcuts --remove` takes it away).

## If pipx isn't available: a plain venv

```
py -m venv %LOCALAPPDATA%\Memex\venv
%LOCALAPPDATA%\Memex\venv\Scripts\pip install memex
```

Run it as `%LOCALAPPDATA%\Memex\venv\Scripts\memex`. Power users may use uv instead.

## Upgrade

Quit Memex first, then run `pipx upgrade memex`. If the upgrade fails because a file is in use, Memex (or a console still running it) is open: quit it and try again.

`memex --version` and Settings show the installed version.
