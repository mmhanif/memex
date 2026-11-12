# Distribution and launch without admin rights

Research for ticket [#17 Installing a Python app without admin rights](https://github.com/mmhanif/memex/issues/17). Researched 2026-11-11.

**Question.** How can a Python 3.14 web app be installed and launched on a locked-down Windows or macOS workstation? The workstation has no admin rights and no outbound internet, but it can reach an internal PyPI mirror. The ticket asks about four things:

- the install routes (`pip install --user`, a venv, `pipx`, `uv tool install`, a zipapp/shiv/pex, or a vendored wheelhouse);
- launchers and shortcuts;
- opening the browser and choosing a port, alongside the launch secret from [localhost-hardening.md](localhost-hardening.md);
- how the vendored ESM files from [frontend-libraries.md](frontend-libraries.md) get into the wheel.

**Short answer.**

- **Ship Memex as one pure-Python wheel (`py3-none-any`) on the internal mirror.** The vendored front end goes inside the package as package data. A dev-machine script fetches it and it is committed to git, so building the wheel needs no network.
- **Install it with `pipx`.** pipx installs from the same mirror with `python -m pip install --user pipx`, needs no admin rights, uses pip and therefore the user's existing `pip.ini`/`pip.conf` and the OS certificate store, and remembers the index for upgrades.
- **Document a plain venv as the fallback for machines without pipx.** It is the same wheel and two commands.
- **Rule out zipapp, shiv and pex.** Memex's dependency set contains C extensions (`pydantic-core`, plus `pywin32` on Windows through the MCP SDK). A zip cannot load those, so the archive either has to unpack itself into a cache or be built separately for each platform.
- **Launch with a `memex` console script.**
  1. It binds `127.0.0.1` on a fixed default port, and binds the socket itself.
  2. If that port is busy, it first checks whether the listener is a running Memex. It does this with a challenge-response through a per-user state file. It never trusts the listener just because it answers.
  3. If the listener is not Memex, the launcher falls back to the next port or to port 0.
  4. It then opens the browser at the one-time `/auth?code=` URL with `webbrowser.open`.
- **Make shortcuts with an optional `memex shortcuts` subcommand.** It writes a per-user Start-menu `.lnk` on Windows (through `pywin32`, not PowerShell) and a minimal `~/Applications/Memex.app` on macOS.

---

## 1. What the workstation already gives us

- **Python 3.14 is already installed.** On Windows, both of the official ways to get Python 3.14 install per user without elevation:
  - The traditional installer's "Install Now" means "You will *not* need to be an administrator", and its just-for-me path is `%LocalAppData%\Programs\Python\PythonXY` ([Using Python on Windows](https://docs.python.org/3.14/using/windows.html)).
  - The new Python install manager "does not support installing runtimes per-machine" (same page). The exe installer is "deprecated since 3.14 and will not be produced for Python 3.16 or later."

  Either way, `py` (or `python`) is on the user's PATH.
- **Some `pip` settings can come from the admin side, but the user can set the index alone.** The per-user config file is `%APPDATA%\pip\pip.ini` on Windows. On macOS it is `~/Library/Application Support/pip/pip.conf` if that directory exists, and `~/.config/pip/pip.conf` otherwise. `PIP_<UPPER_LONG_NAME>` environment variables override the file ([pip configuration](https://pip.pypa.io/en/stable/topics/configuration/)). A site may already ship a global file (`C:\ProgramData\pip\pip.ini`, `/Library/Application Support/pip/pip.conf`) pointing at the mirror. If it doesn't, the user can set `index-url` in the per-user file without admin rights.
- **TLS to the mirror.** pip has used "system certificates ... in addition to certifi" by default since v24.2 ([pip HTTPS certificates](https://pip.pypa.io/en/stable/topics/https-certificates/)), so a mirror signed by a corporate CA in the OS trust store works out of the box. **uv does not do this:** "By default, uv uses bundled Mozilla root certificates". It needs `--system-certs`, `UV_SYSTEM_CERTS=true` or `system-certs = true` in `uv.toml` ([uv TLS certificates](https://docs.astral.sh/uv/concepts/authentication/certificates/)).
- **The mirror must carry cp314 wheels.** It needs them for `win_amd64` and for macOS (arm64 and/or x86_64) for every compiled dependency: `pydantic-core`, and `pywin32` on Windows, which the MCP SDK pulls in ([mcp-integration.md](mcp-integration.md)). It also needs pure-Python wheels for the rest. Pass `--only-binary :all:` ("Do not use source packages", [pip install](https://pip.pypa.io/en/stable/cli/pip_install/)) so a missing wheel fails loudly instead of trying to compile on a machine with no compiler.

---

## 2. Install routes

| Route | Admin needed? | Custom index / offline wheelhouse | Upgrades | Needs on the machine | Verdict |
|---|---|---|---|---|---|
| `pip install --user memex` | No | `--index-url`, `pip.ini`, or `--no-index --find-links DIR` | `pip install --user -U memex` | pip only | **Avoid.** It shares one user site-packages with every other `--user` tool, so dependency conflicts are likely. The scripts directory is not on PATH by default |
| **venv** (`python -m venv %LOCALAPPDATA%\Memex\venv`, then that venv's `pip install memex`) | No | Same pip options. A site-level `pip.ini` can sit inside the venv | `<venv>\Scripts\python -m pip install -U memex` | stdlib only | **Fallback.** Zero extra tools. The user manages PATH and shortcuts |
| **pipx** (`pipx install memex`) | No | `--index-url`, `--pip-args=...`, `PIP_INDEX_URL`, user `pip.ini` (pip backend). Recorded for upgrades | `pipx upgrade memex` re-uses the recorded index | pipx (pure-Python wheel on PyPI, Python 3.11+) installed via `pip install --user pipx` | **Recommended** |
| **uv tool** (`uv tool install memex`) | No | `--default-index` / `UV_DEFAULT_INDEX`, flat index for wheelhouses. Settings retained for upgrades | `uv tool upgrade memex` | uv (a platform wheel on PyPI) installed via `pip install --user uv` or pipx | **Acceptable alternative.** Needs `UV_SYSTEM_CERTS` and Python downloads disabled |
| zipapp / shiv / pex | No | Built on the dev machine with pip options | Replace the file | A Python, plus an extraction cache | **Reject.** C extensions (§2.5) |
| Vendored wheelhouse (`pip download` → copy → `--no-index --find-links`) | No | It *is* the offline source | Ship a new wheelhouse | pip | **Contingency** only, for a package missing from the mirror |

### 2.1 `pip install --user`

- `--user` installs "to the Python user install directory for your platform" ([pip install](https://pip.pypa.io/en/stable/cli/pip_install/)). That directory is `site.USER_BASE`:
  - `%APPDATA%\Python` on Windows;
  - `~/Library/Python/X.Y` on macOS framework builds (the python.org installer);
  - `~/.local` elsewhere ([site](https://docs.python.org/3.14/library/site.html)).
- Scripts land in `%APPDATA%\Python\Python314\Scripts` or `~/Library/Python/3.14/bin` ([sysconfig user schemes](https://docs.python.org/3.14/library/sysconfig.html)). Neither is on PATH by default, and pip only warns about it (`--no-warn-script-location`).
- The real problem is isolation. Memex pins FastAPI, pydantic, the MCP SDK, uvicorn and so on, and every other `--user` tool shares that one site-packages. The only good use of `--user` here is to **bootstrap pipx or uv**.

### 2.2 A venv

- `python -m venv` needs nothing beyond the stdlib.
- Scripts in a venv "should be runnable without activating it", because their shebang points at the venv's interpreter ([venv](https://docs.python.org/3.14/library/venv.html)). So `%LOCALAPPDATA%\Memex\venv\Scripts\memex.exe` can be the target of a shortcut, or the `command` in an MCP client config.
- **Caveats** (same page):
  - Environments are "not considered as movable or copyable", so never copy a venv between machines.
  - After a Python upgrade, use `--upgrade` or recreate the venv.
  - On Windows, symlinks are "not recommended", so keep the default copies.
- **Index.** pip's *site* config file is `%VIRTUAL_ENV%\pip.ini` (`$VIRTUAL_ENV/pip.conf` on macOS) ([pip configuration](https://pip.pypa.io/en/stable/topics/configuration/)). An install script could drop the mirror URL there so it applies only to Memex's venv.

### 2.3 pipx

- **Bootstrapping.** `py -m pip install --user pipx`, then `pipx ensurepath`, which "adds both that directory and `%USERPROFILE%\.local\bin` to your search path". This needs pip 19.0+, and "Installing pipx needs Python 3.11 or newer" ([install pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html)). The only installs that page marks as needing `sudo` are the `--global` ones. A pipx zipapp (`pipx.pyz`) also exists, but it comes from GitHub releases, so it is not reachable from the mirror.
- **Where it installs.** `PIPX_HOME` is `%LOCALAPPDATA%\pipx\pipx` on Windows and `~/Library/Application Support/pipx` on macOS. App links go to `PIPX_BIN_DIR`, which defaults to `~/.local/bin` ([pipx environment variables](https://pipx.pypa.io/stable/reference/environment-variables.html)). All of this sits under the user profile.
- **Private index.** It is set per command with `--index-url` or `--pip-args`, or for every command with `PIP_INDEX_URL`. pipx "removes pip's site-level file ... in the root of the venv", so the setting belongs in the user or global pip config. "pipx records these options and passes them again on `pipx upgrade` and `pipx reinstall`" ([pipx private index](https://pipx.pypa.io/stable/how-to/use-private-index.html)).
- **Backends.** pipx can use pip or uv. The uv backend ignores `PIP_*` variables ([configure paths](https://pipx.pypa.io/stable/how-to/configure-paths.html)), so keep the default pip backend to inherit the existing pip config.
- **Upgrades.**
  - `pipx upgrade memex` upgrades Memex.
  - `python -m pip install --user --upgrade pipx` upgrades pipx itself ([upgrade pipx](https://pipx.pypa.io/stable/how-to/upgrade-pipx.html)).
  - After a Python minor upgrade, `pipx reinstall-all` rebuilds the venvs.
- **What it gives Memex for free.** An isolated venv, a stable executable path for the MCP client config (`~/.local/bin/memex-mcp[.exe]`), PATH set-up, and an upgrade that remembers the index.

### 2.4 `uv tool install`

- **Getting uv.** "uv is published to PyPI", so pipx or pip can install it from the mirror ([uv installation](https://docs.astral.sh/uv/getting-started/installation/)). The standalone installer fetches from the internet, so it is unusable here.
- **Where tools go.** Each tool gets its own venv in the uv tools directory, and executables are copied (Windows) or symlinked into the executable directory, which "must be in the `PATH`" ([uv tools](https://docs.astral.sh/uv/concepts/tools/)). That directory is `%USERPROFILE%\.local\bin` or `~/.local/bin` ([uv storage](https://docs.astral.sh/uv/reference/storage/)).
- **Upgrades.** "Tool upgrades will retain the settings provided when installing the tool."
- **Index.** `--default-index` or `UV_DEFAULT_INDEX` sets the index. `UV_INDEX_URL` still works but is "Deprecated: use `UV_DEFAULT_INDEX` instead". `UV_OFFLINE` "will disable network access" ([uv environment variables](https://docs.astral.sh/uv/reference/environment/)). A wheelhouse is a `format = "flat"` index, the equivalent of pip's `--find-links` ([uv indexes](https://docs.astral.sh/uv/concepts/indexes/)).
- **Three extra settings an air-gapped machine needs:**
  1. system certificates (§1);
  2. "By default, uv will automatically download Python versions when needed", so set `python-preference = "only-system"` and turn downloads off ([uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/));
  3. the index itself, in `%APPDATA%\uv\uv.toml` or `~/.config/uv/uv.toml` ([uv storage](https://docs.astral.sh/uv/reference/storage/)). uv does not read `pip.ini`.
- **Verdict.** uv works and is faster. Compared with pipx it adds a native binary and three configuration pitfalls for no functional gain on a single-app install.

### 2.5 zipapp, shiv, pex

- **zipapp (stdlib).** You bundle dependencies with `pip install -r requirements.txt --target myapp` and then run `python -m zipapp`. But "If your application depends on a package that includes a C extension, that package cannot be run from a zip file (this is an OS limitation...)". You would have to ship the binaries alongside the archive and manage `sys.path` for each architecture yourself ([zipapp](https://docs.python.org/3.14/library/zipapp.html)). `pydantic-core` is such a package, so a plain `.pyz` is not viable.
- **shiv.** It solves the C-extension problem by unpacking "the dependencies into a uniquely named subdirectory of `~/.shiv`", because "shared objects loaded via the dlopen syscall require a regular filesystem" ([shiv](https://shiv.readthedocs.io/en/latest/)). The costs:
  - The `.pyz` holds platform wheels, so it must be built once per OS and architecture.
  - It leaves an extraction cache in the profile.
  - Its docs do not mention Windows.
- **pex.** Its docs document cross-building with `--platform` / `--complete-platform` and offline resolution with `--no-index` plus `-f/--find-links` ([building .pex files](https://docs.pex-tool.org/buildingpex.html)). The build docs make no Windows support statement, which is a red flag for half the fleet.
- **Verdict.** A single file is attractive, but each tool either cannot load `pydantic-core` or reinvents a venv in a hidden cache with a platform-specific build. Upgrading still means replacing a file. None of this beats `pipx upgrade`.

### 2.6 Vendored wheelhouse

pip documents the pattern: `pip download --destination-directory DIR -r requirements.txt` on a connected machine, then install "from local only" with `--find-links` and `--no-index` ([pip user guide](https://pip.pypa.io/en/stable/user_guide/)). pipx (`--pip-args="--no-index --find-links=DIR"`) and uv (a flat index) can consume the same directory. Keep it as the contingency for a dependency the mirror lacks. Getting a wheelhouse onto an air-gapped machine is a media-transfer question for the security team, not a design choice.

---

## 3. Launchers and shortcuts

### 3.1 Entry points

Declare these in `pyproject.toml` under `[project.scripts]`:

- `memex = "memex.cli:main"` starts the server and opens the browser.
- `memex-mcp = "memex.mcp:main"` is the stdio MCP server ([mcp-integration.md](mcp-integration.md)).

Installers create wrappers in the scheme's scripts directory but "are not responsible for adding that directory to `PATH`" ([entry points spec](https://packaging.python.org/en/latest/specifications/entry-points/)). pipx and uv do the PATH part.

**Console vs GUI on Windows.** "`console_scripts` are wrapped in a console executable, so they are attached to a console", while "`gui_scripts` ... can be started without a console" but "cannot use standard streams unless application code redirects them". "Other platforms do not have the same distinction" (same spec). Options:

- **Console only (simplest).** The shortcut opens a console window that shows the log and the URL, and closing it stops Memex. It is honest and debuggable.
- **Add a `[project.gui-scripts] memexw = ...`** for a windowless start. Memex then needs another way to stop (a "Quit" action in the UI, or exit when idle) and must log to a file. **This is a decision for the grilling ticket.**

### 3.2 Shims

With pipx or uv the shim is the generated `memex.exe`, or `memex` in `~/.local/bin`. With a bare venv it is `<venv>\Scripts\memex.exe` or `<venv>/bin/memex`. Separate `.cmd` or `.command` files add nothing on Windows. On macOS, a `.command` file opens in Terminal when double-clicked, provided it is executable. That is community-documented behaviour; there is no Apple reference page. It is a quick no-tools shortcut.

### 3.3 Windows Start menu without admin

- **Where to put it.** The per-user Start-menu folder is `FOLDERID_Programs` = `%APPDATA%\Microsoft\Windows\Start Menu\Programs` (folder type PERUSER). The all-users variant `FOLDERID_CommonPrograms` (`%ALLUSERSPROFILE%\...`) is the one that needs admin ([KNOWNFOLDERID](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)). A `.lnk` written to the per-user folder appears in Start, where the user can pin it.
- **How to create it.** A `.lnk` is a Shell link created through `IShellLink` + `IPersistFile`. It stores the target, the arguments, the working directory, the show command and the icon ([Shell Links](https://learn.microsoft.com/en-us/windows/win32/shell/links)).
- **Use pywin32, not PowerShell.** From Python the clean way is `win32com.client` (pywin32), which Memex already gets on Windows through the MCP SDK. Do **not** shell out to PowerShell's `New-Object -ComObject WScript.Shell`. Under AppLocker or WDAC, "PowerShell automatically runs in `ConstrainedLanguage` mode", and that mode permits only the `Scripting.Dictionary`, `Scripting.FileSystemObject` and `VBScript.RegExp` COM types ([about_Language_Modes](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_language_modes)). Locked-down corporate desktops are exactly where those policies run.
- **Caveat.** An AppLocker or WDAC policy could also block executables under `%LOCALAPPDATA%` or `~\.local\bin`, which would block `memex.exe` itself. This cannot be researched from outside. **The grilling ticket should get IT to confirm that pipx-installed console scripts are allowed to run.**

### 3.4 macOS Dock without admin

- A minimal app bundle is `Memex.app/Contents/{Info.plist, MacOS/<exe>}`. The `MacOS/` directory is "(Required)". For Finder to recognise the bundle "you need to include an information property list (`Info.plist`) file", with `CFBundleExecutable` and `CFBundlePackageType = APPL` among the expected keys ([Bundle Programming Guide](https://developer.apple.com/library/archive/documentation/CoreFoundation/Conceptual/CFBundles/BundleTypes/BundleTypes.html)).
- The executable can be a two-line shell script that `exec`s the pipx `memex` shim. Written into `~/Applications`, it can be dragged to the Dock.
- Gatekeeper checks software downloaded from outside the App Store, and the Apple security guide also says software is checked "the first time it's opened, regardless of how it arrived" ([Gatekeeper](https://support.apple.com/guide/security/gatekeeper-and-runtime-protection-sec5599b66df/web)). An unsigned, locally generated script bundle is the low-risk case, but nobody has verified it on a managed Mac. **Test it on a real workstation before promising Dock support.** The `.command` file is the fallback.

**Recommendation.** Ship `memex shortcuts [--remove]` as an opt-in subcommand rather than an install-time side effect. pipx and pip have no post-install hooks, which this research infers from the absence of any such option in the entry-points spec and the pipx docs.

---

## 4. Opening the browser

- **Return value.** `webbrowser.open(url)` "Returns `True` if a browser was successfully launched, `False` otherwise". On non-Unix platforms "the controlling process will not wait" ([webbrowser](https://docs.python.org/3.14/library/webbrowser.html)). Requests for a new tab or window are honoured only "if possible".
- **Windows.** The default controller is `WindowsDefault`, which calls `os.startfile(url)` and returns `False` on `OSError` ([CPython `Lib/webbrowser.py`, 3.14](https://github.com/python/cpython/blob/3.14/Lib/webbrowser.py)). The URL therefore goes to the user's default browser through the shell. It can also appear on that browser's command line, where other same-user processes can see it.
- **macOS.** The controller is `MacOSXOSAScript('default')`. For http(s) URLs it pipes `open location "<url>"` to `/usr/bin/osascript` on stdin (same source).
- **`BROWSER` variable.** It overrides the choice, and in 3.14 it "can now also be used to reorder the list of platform defaults" (docs above). A `chrome` controller exists, but it relies on a command on PATH, which Chrome on Windows and macOS usually isn't. So use the default browser, and let `BROWSER` or a `--browser` option override it.
- **The URL carries the one-time code.** Per [localhost-hardening.md §3](localhost-hardening.md), the code is invalidated on first use, so its exposure on a command line or in history is harmless once it has been redeemed.
- **Always print the URL** to the console as well. `webbrowser.open` can return `True` without anything visible happening, for example when a browser is blocked by policy.
- **Order.** Open the browser only after the socket is listening (§5), so the first request never races the server start.

---

## 5. Choosing a port, and "already running"

**Fixed default vs port 0.**

- uvicorn accepts port 0: "If set to 0, an available port will be picked" ([uvicorn settings](https://uvicorn.dev/settings/)).
- An origin is (scheme, host, port), so a new port every launch is a new origin to the browser. `localStorage`, IndexedDB, any site permissions and the user's bookmark all reset each time.
- A **fixed default port**, overridable in config or with `--port`, gives a stable `http://127.0.0.1:<port>/` the user can bookmark. The bookmark just lands on the "please relaunch" page if Memex isn't running, and is fine once the session cookie exists. Use port 0 only as the fallback.

**Bind the socket yourself, then hand it to uvicorn.**

- `uvicorn.Server.run(sockets=[sock])` / `serve(sockets=...)` accepts already-open sockets ([uvicorn `server.py`](https://github.com/Kludex/uvicorn/blob/main/uvicorn/server.py)). The launcher knows the real port from `sock.getsockname()` ([socket](https://docs.python.org/3.14/library/socket.html)) before it builds the auth URL, as localhost-hardening R3 requires.
- On Windows set `SO_EXCLUSIVEADDRUSE` before `bind`, per [localhost-hardening.md §3](localhost-hardening.md). CPython exports the constant when the platform headers define it ([`socketmodule.c`](https://github.com/python/cpython/blob/3.14/Modules/socketmodule.c)).
- On POSIX, `socket.create_server` sets `SO_REUSEADDR` "to immediately reuse previous sockets ... in TIME_WAIT state" ([socket](https://docs.python.org/3.14/library/socket.html)). That is fine.

**If the port is busy:**

1. The running instance writes a state file under the user profile (`%LOCALAPPDATA%\Memex\run.json` or `~/Library/Application Support/Memex/run.json`, mode `0600`). It holds `{pid, port, control_secret}` and is removed on clean exit.
2. A second `memex` reads the file. If the PID is alive, it sends the listener a random nonce, and Memex must answer `HMAC(control_secret, nonce)`. A squatter cannot. Only after that check does the launcher ask the instance to mint a fresh one-time code (authenticated the same way), then open the browser at that URL. This is the `memex open` behaviour that localhost-hardening anticipates, and it never sends a secret to an unverified listener.
3. If the file is missing or stale, or the challenge fails, treat the port as taken by something else. Bind the next port in a small range, or port 0, and warn that the bookmark will not match this session.

The grilling ticket should confirm the default port number and the fallback policy (range vs port 0).

---

## 6. Vendored front-end files: fetch, refresh, ship

**Fetch on a connected dev machine, commit, never fetch at install time.**

- Add a `scripts/vendor.py` (dev-only, not in the wheel) that reads a pinned manifest, `src/memex/static/vendor/VERSIONS` (suggested in [frontend-libraries.md](frontend-libraries.md)), with package, version, the files to copy and the expected `integrity`.
- For each entry the script does four things:
  1. downloads the registry tarball, either `npm pack <name>@<version>`, which saves `<name>-<version>.tgz` in the current directory ([npm pack](https://docs.npmjs.com/cli/v11/commands/npm-pack)), or a plain HTTP fetch of `dist.tarball`;
  2. checks the tarball against `dist.integrity` from the registry metadata, an SRI string `<hashAlgorithm>-<base64-hash>` ([npm registry package metadata](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md));
  3. extracts only the listed browser files plus `LICENSE*`;
  4. writes them under `src/memex/static/vendor/<pkg>/`.
- Optional one-off bundles (CodeMirror via esbuild) follow the same script, and their output is committed too.
- **Refresh** = bump the version in `VERSIONS`, re-run the script, review the diff (including a grep for `http(s)://` as in frontend-libraries.md's method) and commit. The workstation never runs any of this.

**Ship as package data.** Put `static/` *inside* the import package (`src/memex/static/...`) and serve it via `importlib.resources`. Setuptools "strongly recommended" `importlib.resources` over `__file__` paths, because of zip imports ([setuptools data files](https://setuptools.pypa.io/en/latest/userguide/datafiles.html)). Then:

- **hatchling.** With no file-selection options, the wheel ships `src/<NAME>/` ([hatch wheel builder](https://hatch.pypa.io/latest/plugins/builder/wheel/)), and Hatch "will respect the first `.gitignore`" ([hatch build config](https://hatch.pypa.io/latest/config/build/)). Because the vendored files are committed and not ignored, they are included with zero configuration. If they ever are generated and git-ignored, list them under `artifacts`.
- **setuptools.** `include-package-data` defaults to true with `pyproject.toml`. That only picks up files that MANIFEST.in or a VCS plugin (setuptools-scm) selects. Alternatively, list them explicitly with `[tool.setuptools.package-data]` globs, which "neither require to be included within a MANIFEST.in file, nor require to be added by a revision control system plugin" (setuptools data files).
- **Check before every release.** Unzip the built wheel and assert that `memex/static/vendor/VERSIONS` and every listed file is present. This is a CI test, not a manual step.

**Uvicorn/Starlette `StaticFiles` needs a real directory.** Because the package is installed unzipped into a venv (pipx, uv or venv), `importlib.resources.files("memex") / "static"` is a real path. That is one more reason to avoid the zip-based routes in §2.5.

---

## 7. Recommendation (for the grilling ticket to confirm)

1. **Artefact.** One pure-Python `memex` wheel built with hatchling, with the vendored ESM, CSS and fonts under `memex/static/` as package data, published to the internal mirror. Dependencies install as wheels only (`--only-binary :all:`), so the mirror must carry cp314 wheels for `win_amd64` and macOS.
2. **Install.** Use `py -m pip install --user pipx`, `pipx ensurepath`, then `pipx install memex`, with the mirror set in the user's `pip.ini`/`pip.conf` or by IT globally. Upgrade with `pipx upgrade memex`. Document a two-command venv in `%LOCALAPPDATA%\Memex\venv` / `~/Library/Application Support/Memex/venv` as the no-pipx fallback. uv is an acceptable power-user alternative with the three settings in §2.4. Do not offer zipapp, shiv or pex.
3. **Launch.** A `memex` console script that:
   - binds 127.0.0.1 on a fixed default port (exclusive on Windows);
   - detects a running instance through the state file plus a challenge-response;
   - falls back to another port only for squatters;
   - serves on the pre-bound socket with uvicorn;
   - opens `webbrowser.open("http://127.0.0.1:PORT/auth?code=…")` after listening starts, and prints the URL.

   Plus `memex-mcp` for stdio MCP.
4. **Shortcuts.** An opt-in `memex shortcuts` subcommand: a per-user Start-menu `.lnk` via pywin32, and `~/Applications/Memex.app` (or a `.command` file) on macOS.

### Open questions for the grilling ticket ([#18](https://github.com/mmhanif/memex/issues/18))

- **pipx availability.** Is `pipx` on the mirror? It is pure Python and MIT-licensed. Does IT already ship a global `pip.ini`, or must users write the index URL themselves?
- **Application control.** Do AppLocker, WDAC or the Mac MDM allow executables in `~/.local/bin` and `%LOCALAPPDATA%`? If not, every route here fails equally, and IT must allowlist the path or the publisher.
- **Console window vs windowless.** Console window (`console_scripts`, stop by closing it), or windowless (`gui_scripts` + a Quit action + a log file)?
- **Default port number** and the fallback policy: next N ports vs port 0.
- **Shortcuts.** Must they be created automatically, or is an opt-in subcommand enough? Must the macOS `.app` be signed, or is it tolerated unsigned under the fleet's Gatekeeper/MDM settings?
- **Mirror architectures.** Which macOS architectures must the mirror carry wheels for (arm64 only, or x86_64 too)?
