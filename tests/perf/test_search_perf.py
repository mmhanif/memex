"""SPEC §16.8: search holds p95 ≤ 50 ms on a 5,000-file / 50 MB Workspace.

Not part of the default run: `pytest tests/perf --run-perf`.
"""

import statistics
import time
from pathlib import Path

import pytest

from memex.core.search import search
from memex.core.workspace import NewMe, apply_setup
from tests.perf.generator import FILES, build

pytestmark = pytest.mark.perf

BUDGET_MS = 50
QUERIES = (
    # fuzzy names and prefixes
    "dmig",
    "migr",
    "roadmap",
    "project-12",
    "person-1",
    "wrhs",
    "cafe",
    "jose",
    "rvw dck",
    "plat sec",
    # phrases
    '"revised deck"',
    '"customer retention"',
    '"api gateway"',
    '"warehouse cutover"',
    # body words
    "postmortem latency",
    "invoice compliance",
    "offsite",
    "naive resume",
    "forecast metrics",
    # filters, alone and with text
    "type:project status:active",
    "type:project @person-3",
    "type:todo due:this-week",
    "due:overdue",
    "label:budget",
    "type:note @person-7 hiring",
    "status:blocked roadmap",
    "type:glossary-term api",
    "type:deliverable,project launch",
    "due<2026-12-01 type:project",
    "label:vendor contract",
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("perf") / "ws"
    build(root)
    ws = apply_setup(root, NewMe("Ada"), install_dir=root.parent / "install")
    assert len(ws.cache.files()) >= FILES
    return ws


def test_search_p95_is_within_budget(workspace):
    for q in QUERIES:  # warm-up: builds the folded index
        search(workspace, q)
    timings = []
    for _ in range(3):
        for q in QUERIES:
            start = time.perf_counter()
            search(workspace, q)
            timings.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(timings, n=20)[-1]
    print(f"search p95 {p95:.1f} ms over {len(timings)} runs; max {max(timings):.1f} ms")
    assert p95 <= BUDGET_MS, f"p95 {p95:.1f} ms > {BUDGET_MS} ms: time for SQLite FTS5 (§9.1)"


def test_the_generator_is_about_fifty_megabytes(workspace):
    total = sum(p.stat().st_size for p in Path(workspace.root).rglob("*.md"))
    assert 45_000_000 <= total <= 55_000_000
