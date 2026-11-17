"""Check a built wheel for the package job (SPEC §13.6, §16.5, §16.9). Dev only: not in the wheel.

1. Every file listed in static/vendor/VERSIONS is in the wheel.
2. No file in the wheel (Python and static alike) names an outside host: the running
   app must never reach beyond 127.0.0.1. Licence files, XML namespace names (never
   fetched) and a few links in vendored comments are allowed.

    uv run scripts/check_wheel.py dist/memex-*.whl
"""

import re
import sys
import tomllib
import zipfile
from pathlib import PurePosixPath

VERSIONS = "memex/static/vendor/VERSIONS"
URL = re.compile(r"https?://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s\"'`)<>\\]*")
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".css", ".html", ".svg", ".json", ".md", ".txt", ""}

# XML namespace names are identifiers, not requests; allowed in static files only.
NAMESPACE_HOSTS = {"www.w3.org"}
# Links in comments of vendored files, by file and URL.
ALLOWED = {
    (
        "memex/static/vendor/markdown-it/dist/browser/markdown-it.esm.min.mjs",
        "https://github.com/markdown-it/markdown-it",
    ),
    (
        "memex/static/vendor/dompurify/dist/purify.es.mjs",
        "https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE",
    ),
    (
        "memex/static/vendor/dompurify/dist/purify.es.mjs",
        "https://github.com/sindresorhus/validate-element-name",
    ),
    (
        "memex/static/vendor/dompurify/dist/purify.es.mjs",
        "https://bugs.chromium.org/p/chromium/issues/detail?id=1305293",
    ),
}


def missing_vendor_files(whl: zipfile.ZipFile) -> list[str]:
    names = set(whl.namelist())
    if VERSIONS not in names:
        return [VERSIONS]
    manifest = tomllib.loads(whl.read(VERSIONS).decode("utf-8"))
    expected = [
        f"memex/static/vendor/{package}/{file}"
        for package, spec in manifest["packages"].items()
        for file in spec["files"]
    ]
    return [name for name in expected if name not in names]


def outbound_urls(whl: zipfile.ZipFile) -> list[tuple[str, str]]:
    found = []
    for name in whl.namelist():
        path = PurePosixPath(name)
        if path.name.upper().startswith("LICENSE") or ".dist-info/" in name:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or name.endswith("/"):
            continue
        text = whl.read(name).decode("utf-8", errors="replace")
        for url in URL.findall(text):
            host = url.split("://", 1)[1].split("/", 1)[0]
            namespace = host in NAMESPACE_HOSTS and name.startswith("memex/static/")
            if not namespace and (name, url) not in ALLOWED:
                found.append((name, url))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_wheel.py WHEEL", file=sys.stderr)
        return 2
    with zipfile.ZipFile(argv[0]) as whl:
        missing = missing_vendor_files(whl)
        urls = outbound_urls(whl)
    for name in missing:
        print(f"missing from the wheel: {name}")
    for name, url in urls:
        print(f"outbound URL: {name}: {url}")
    if missing or urls:
        return 1
    print(f"{argv[0]}: every VERSIONS file present, no outbound URLs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
