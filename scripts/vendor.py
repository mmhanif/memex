"""Refresh the vendored front-end files from npm (SPEC §13.6). Dev only: not in the wheel.

For each package in src/memex/static/vendor/VERSIONS: download the tarball, check it
against the pinned `dist.integrity`, and write only the listed files (browser files and
licences) under vendor/<package>/. The output is committed; workstations never fetch.

    uv run scripts/vendor.py
"""

import base64
import hashlib
import io
import shutil
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path, PurePosixPath

VENDOR = Path(__file__).resolve().parent.parent / "src/memex/static/vendor"
REGISTRY = "https://registry.npmjs.org"


def main() -> int:
    manifest = tomllib.loads((VENDOR / "VERSIONS").read_text("utf-8"))
    for name, pkg in manifest["packages"].items():
        tarball = _download(name, pkg["version"])
        _check_integrity(name, tarball, pkg["integrity"])
        _extract(name, tarball, pkg["files"])
        print(f"{name}@{pkg['version']}: {len(pkg['files'])} files")
    return 0


def _download(name: str, version: str) -> bytes:
    url = f"{REGISTRY}/{name}/-/{name.split('/')[-1]}-{version}.tgz"
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _check_integrity(name: str, tarball: bytes, integrity: str) -> None:
    algorithm, _, expected = integrity.partition("-")
    actual = base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode("ascii")
    if actual != expected:
        raise SystemExit(f"{name}: tarball doesn't match the pinned integrity")


def _extract(name: str, tarball: bytes, files: list[str]) -> None:
    dest = VENDOR / name
    shutil.rmtree(dest, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for rel in files:
            if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
                raise SystemExit(f"{name}: bad file path {rel!r} in VERSIONS")
            member = tar.extractfile(f"package/{rel}")
            if member is None:
                raise SystemExit(f"{name}: {rel} isn't a file in the tarball")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(member.read())


if __name__ == "__main__":
    sys.exit(main())
