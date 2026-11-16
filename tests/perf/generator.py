"""A seeded synthetic Workspace for the search perf job (SPEC §16.8): about 5,000 files
and 50 MB, in a realistic type mix."""

import datetime as dt
import itertools
import random
from pathlib import Path

from memex.core import frontmatter

FILES = 5_000
TARGET_BYTES = 50_000_000

# (folder, count, average body bytes); notes carry most of the text.
MIX = (
    ("themes", 25, 2_000),
    ("projects", 300, 6_000),
    ("deliverables", 900, 3_000),
    ("people", 200, 1_500),
    ("todos", 1_400, 300),
    ("glossary", 125, 800),
    ("notes", 2_050, 0),  # takes what's left of the target
)

KNOWN_WORDS = [
    "migration",
    "warehouse",
    "roadmap",
    "budget",
    "hiring",
    "review",
    "cutover",
    "vendor",
    "contract",
    "latency",
    "revised",
    "deck",
    "quarterly",
    "planning",
    "platform",
    "security",
    "audit",
    "onboarding",
    "café",
    "résumé",
    "José",
    "naïve",
    "customer",
    "retention",
    "pipeline",
    "incident",
    "postmortem",
    "launch",
    "metrics",
    "forecast",
    "design",
    "system",
    "api",
    "gateway",
    "billing",
    "invoice",
    "compliance",
    "training",
    "offsite",
    "strategy",
]
VOCABULARY = 20_000
_SYLLABLES = [c + v for c in "bcdfghjklmnprstvwz" for v in ("a", "e", "i", "o", "u", "ai", "ou")]


def _vocabulary(rng: random.Random) -> list[str]:
    """Realistic prose: the known words, then made-up ones, used with Zipf frequencies."""
    made = {"".join(rng.choices(_SYLLABLES, k=rng.randint(1, 4))) for _ in range(VOCABULARY)}
    return [*KNOWN_WORDS, *sorted(made)]


def build(root: Path, seed: int = 8) -> None:
    rng = random.Random(seed)
    vocabulary = _vocabulary(rng)
    zipf = list(itertools.accumulate(1 / rank for rank in range(1, len(vocabulary) + 1)))
    used = sum(count * size for _, count, size in MIX)
    notes = next(count for folder, count, _ in MIX if folder == "notes")
    note_size = (TARGET_BYTES - used) // notes
    people = [f"person-{n}" for n in range(200)]
    projects = [f"project-{n}" for n in range(300)]
    for folder, count, size in MIX:
        (root / folder).mkdir(parents=True, exist_ok=True)
        for n in range(count):
            title = " ".join(rng.choice(KNOWN_WORDS) for _ in range(3)).title()
            fields: dict[str, object] = {"title": title}
            if folder == "projects":
                fields |= {"status": rng.choice(["active", "blocked", "done", "not-started"])}
                fields |= {"lead": rng.choice(people), "theme": f"theme-{n % 25}"}
                fields |= {"due": dt.date(2026, 11, 1) + dt.timedelta(days=rng.randrange(90))}
            elif folder == "deliverables":
                fields |= {"status": "active", "project": rng.choice(projects)}
            elif folder == "people":
                fields |= {"kind": ["team-member"], "role": rng.choice(KNOWN_WORDS)}
            elif folder == "todos":
                fields |= {"status": "open", "owner": rng.choice(people), "requester": "person-0"}
            elif folder == "glossary":
                fields |= {"aliases": [rng.choice(KNOWN_WORDS).upper()]}
            elif folder == "notes":
                fields |= {"people": rng.sample(people, 2), "labels": [rng.choice(KNOWN_WORDS)]}
            body = _prose(rng, vocabulary, zipf, size or note_size)
            stem = {"themes": "theme", "projects": "project", "people": "person"}.get(folder)
            name = f"{stem}-{n}" if stem else f"{folder}-{n}"
            text = frontmatter.with_fields("", fields) + body
            (root / folder / f"{name}.md").write_text(text, "utf-8")


def _prose(rng: random.Random, vocabulary: list[str], zipf: list[float], size: int) -> str:
    lines: list[str] = []
    total = 0
    while total < size:
        words = rng.choices(vocabulary, cum_weights=zipf, k=rng.randrange(6, 16))
        line = " ".join(words) + ".\n"
        lines.append(line)
        total += len(line.encode())
    return "".join(lines)
