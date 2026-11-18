"""Memex: a personal, offline workspace stored as plain Markdown files."""

from importlib import metadata


def version() -> str:
    """The installed version, or "dev" when run from a checkout with no install."""
    try:
        return metadata.version("memex")
    except metadata.PackageNotFoundError:
        return "dev"
