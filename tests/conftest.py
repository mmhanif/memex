import sys

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-perf", action="store_true", help="run the search perf job (§16.8)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_perf = pytest.mark.skip(reason="perf job: pass --run-perf")
    skip_windows = pytest.mark.skip(reason="Windows-only test")
    for item in items:
        if "perf" in item.keywords and not config.getoption("--run-perf"):
            item.add_marker(skip_perf)
        if "windows" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_windows)
