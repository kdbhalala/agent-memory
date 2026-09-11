#!/usr/bin/env python3
"""Helper script to update Formula/agent-memory.rb with release version and sha256."""
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

FORMULA_PATHS = [
    Path(__file__).resolve().parent.parent / "Formula" / "agi-memory.rb",
    Path(__file__).resolve().parent.parent / "Formula" / "agent-memory.rb",
]


def update_formula(version: str, sha256_hash: str | None = None) -> None:
    tarball_url = f"https://github.com/kdbhalala/agi-memory/archive/refs/tags/v{version}.tar.gz"

    if not sha256_hash:
        print(f"Fetching {tarball_url} to compute sha256...")
        req = urllib.request.Request(tarball_url, headers={"User-Agent": "agi-memory-release"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            sha256_hash = hashlib.sha256(data).hexdigest()
        print(f"Calculated sha256: {sha256_hash}")

    for f_path in FORMULA_PATHS:
        if f_path.exists():
            content = f_path.read_text(encoding="utf-8")
            content = re.sub(r'url ".*?"', f'url "{tarball_url}"', content)
            content = re.sub(r'sha256 ".*?"', f'sha256 "{sha256_hash}"', content)
            f_path.write_text(content, encoding="utf-8")
            print(f"Updated {f_path} for v{version} (sha256: {sha256_hash})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 packaging/update_formula.py <version> [sha256]")
        sys.exit(1)
    ver = sys.argv[1].lstrip("v")
    sha = sys.argv[2] if len(sys.argv) > 2 else None
    update_formula(ver, sha)
