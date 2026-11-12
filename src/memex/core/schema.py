"""Entity types and their fields (SPEC §2, §4.3)."""

from enum import StrEnum


class EntityType(StrEnum):
    THEME = "theme"
    PROJECT = "project"
    DELIVERABLE = "deliverable"
    PERSON = "person"
    TODO = "todo"
    GLOSSARY_TERM = "glossary-term"

    @property
    def folder(self) -> str:
        return _FOLDERS[self]

    @classmethod
    def for_folder(cls, folder: str) -> EntityType | None:
        return _BY_FOLDER.get(folder)


_FOLDERS = {
    EntityType.THEME: "themes",
    EntityType.PROJECT: "projects",
    EntityType.DELIVERABLE: "deliverables",
    EntityType.PERSON: "people",
    EntityType.TODO: "todos",
    EntityType.GLOSSARY_TERM: "glossary",
}
_BY_FOLDER = {folder: t for t, folder in _FOLDERS.items()}


# Frontmatter fields that hold Ids, by type; None is a Note (§4.3, §4.5).
REFERENCE_FIELDS: dict[EntityType | None, tuple[str, ...]] = {
    EntityType.THEME: ("lead", "team", "stakeholders"),
    EntityType.PROJECT: ("theme", "lead", "team", "stakeholders"),
    EntityType.DELIVERABLE: ("project", "lead", "team", "stakeholders"),
    EntityType.PERSON: ("manager",),
    EntityType.TODO: ("owner", "requester", "about", "source"),
    EntityType.GLOSSARY_TERM: (),
    None: ("people", "about"),
}
