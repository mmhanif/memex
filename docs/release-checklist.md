# Release checklist

A manual check of about ten minutes, run on the real Windows workstation before a Memex version is announced as usable. It covers what GitHub-hosted runners can't: the corporate mirror, endpoint and antivirus file locks, execution policy, and the real Chrome build. See [SPEC.md §16.10](../SPEC.md#1610-release-check).

Version under test: `________`  Date: `________`  Result: pass / fail

## Install or upgrade

- [ ] `pipx install memex` (new machine) or `pipx upgrade memex` (with Memex quit) succeeds from the mirror, with no index flags.
- [ ] `memex --version` prints the version under test.

## First run

- [ ] `memex` opens Chrome at `http://127.0.0.1:47615/…`, and the console shows the URL and log.
- [ ] On a fresh profile: Setup creates a Workspace at the chosen path, asks for your name, and lands on the Dashboard's "get started" panel.
- [ ] On an existing Workspace: it opens straight to the Dashboard.

## Everyday use

- [ ] Create a Note from the Meeting Template, type in it, and see it auto-save (check the file in Explorer or VS Code).
- [ ] Create a Project, change its status from the properties card, and add a To-do with quick-add (`+Call vendor @<someone> due:<date>`).
- [ ] Ctrl-K finds the Project by a partial name.

## Outside edits

- [ ] With the Note open (not being edited) in Memex, edit it in VS Code and save: Memex shows "Updated from disk".
- [ ] With unsaved edits in Memex, edit the same file in VS Code: Memex shows the conflict banner, and **Compare** shows the diff.

## Launch and quit

- [ ] Run `memex` again in a second console: it prints "Memex is already running; opened it in your browser" and a working tab opens.
- [ ] **Quit Memex** from Ctrl-K stops the server, and the console returns to the prompt.
- [ ] `memex shortcuts` adds **Memex** to the Start menu and it launches Memex; `memex shortcuts --remove` takes it away.

## Air-gap

- [ ] With DevTools → Network open (Preserve log on), use Memex for a minute, including a Note containing `![](https://example.com/x.png)`. Every request goes to `127.0.0.1`.
