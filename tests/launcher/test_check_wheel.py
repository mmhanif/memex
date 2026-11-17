"""SPEC §13.6, §16.5, §16.9: the package job's wheel checks (scripts/check_wheel.py)."""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/memex/static"
SCRIPT = ROOT / "scripts/check_wheel.py"


def wheel_of(path: Path, *, drop: str | None = None, extra: dict[str, str] | None = None) -> Path:
    """A stand-in wheel holding the real static files, less `drop`, plus `extra`."""
    with zipfile.ZipFile(path, "w") as whl:
        for file in STATIC.rglob("*"):
            name = "memex/static/" + file.relative_to(STATIC).as_posix()
            if file.is_file() and name != drop and "__pycache__" not in name:
                whl.write(file, name)
        for name, text in (extra or {}).items():
            whl.writestr(name, text)
    return path


def check(wheel: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(wheel)], capture_output=True, text=True
    )


def test_a_complete_wheel_passes(tmp_path: Path):
    result = check(wheel_of(tmp_path / "memex.whl"))

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_missing_vendored_file_fails(tmp_path: Path):
    missing = "memex/static/vendor/htm/dist/htm.mjs"

    result = check(wheel_of(tmp_path / "memex.whl", drop=missing))

    assert result.returncode != 0
    assert missing in result.stdout


def test_an_outbound_url_fails(tmp_path: Path):
    extra = {"memex/static/app/leak.js": 'fetch("https://cdn.example.com/x.js");\n'}

    result = check(wheel_of(tmp_path / "memex.whl", extra=extra))

    assert result.returncode != 0
    assert "memex/static/app/leak.js: https://cdn.example.com/x.js" in result.stdout


def test_a_url_in_python_code_fails(tmp_path: Path):
    py = {"memex/core/leak.py": 'URL = "http://telemetry.example.org/v1"\n'}

    result = check(wheel_of(tmp_path / "memex.whl", extra=py))

    assert result.returncode != 0
    assert "memex/core/leak.py: http://telemetry.example.org/v1" in result.stdout
