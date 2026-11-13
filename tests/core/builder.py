"""The Workspace builder (SPEC §16.3): real temp folders with Entities written as files."""

import datetime as dt
from pathlib import Path
from typing import Any

from memex.core import frontmatter
from memex.core.clock import FixedClock
from memex.core.workspace import NewMe, Workspace, apply_setup

TODAY = dt.date(2026, 11, 12)


class Builder:
    """`ws.project("data-migration", theme="platform", lead="alice")` writes the file.

    Me is `ada` (Ada Lovelace). Every write refreshes the Workspace's cache.
    """

    def __init__(self, root: Path, today: dt.date = TODAY) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.clock = FixedClock(today)
        self.ws: Workspace = apply_setup(
            root, NewMe("Ada"), clock=self.clock, install_dir=root.parent / "install"
        )

    def file(self, rel: str, text: str) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        self.ws.changed(rel)
        return rel

    def entity(self, folder: str, id: str, body: str = "", **fields: Any) -> str:
        fields.setdefault("title", id.replace("-", " ").title())
        text = frontmatter.with_fields("", fields) + body
        return self.file(f"{folder}/{id}.md", text)

    def theme(self, id: str, **fields: Any) -> str:
        return self.entity("themes", id, **fields)

    def project(self, id: str, **fields: Any) -> str:
        fields.setdefault("status", "active")
        return self.entity("projects", id, **fields)

    def deliverable(self, id: str, project: str, **fields: Any) -> str:
        fields.setdefault("status", "active")
        return self.entity("deliverables", id, project=project, **fields)

    def person(self, id: str, **fields: Any) -> str:
        fields.setdefault("kind", ["team-member"])
        return self.entity("people", id, **fields)

    def todo(self, id: str, owner: str, requester: str = "ada", **fields: Any) -> str:
        fields.setdefault("status", "open")
        return self.entity("todos", id, owner=owner, requester=requester, **fields)

    def note(self, rel: str, body: str = "", **fields: Any) -> str:
        text = (frontmatter.with_fields("", fields) if fields else "") + body
        return self.file(rel, text)

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text()
