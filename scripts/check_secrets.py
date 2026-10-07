#!/usr/bin/env python3
"""Fail when repository files contain a likely CFBD credential."""

from __future__ import annotations

import re
import math
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAFE_MARKERS = (
    "changeme",
    "dummy",
    "example",
    "placeholder",
    "replace",
    "test",
    "your-",
    "${",
)

ASSIGNMENT = re.compile(
    r"\bCFBD_API_KEY\s*=\s*['\"]?([^\s'\"#]+)", re.IGNORECASE
)
BEARER = re.compile(
    r"\bBearer\s+([A-Za-z0-9_+/=-]{24,})", re.IGNORECASE
)
HIGH_ENTROPY_TOKEN = re.compile(r"(?<![A-Za-z0-9_+/=-])([A-Za-z0-9_+/=-]{48,})(?![A-Za-z0-9_+/=-])")


def repository_files() -> list[Path]:
    """Return tracked and untracked files while respecting .gitignore."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def is_safe_example(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SAFE_MARKERS)


def entropy(value: str) -> float:
    return -sum(
        (value.count(character) / len(value))
        * math.log2(value.count(character) / len(value))
        for character in set(value)
    )


def findings(path: Path) -> list[tuple[int, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for pattern in (ASSIGNMENT, BEARER):
            for match in pattern.finditer(line):
                if not is_safe_example(match.group(1)):
                    matches.append((line_number, pattern.pattern))
        for match in HIGH_ENTROPY_TOKEN.finditer(line):
            value = match.group(1)
            if not is_safe_example(value) and entropy(value) >= 4.3:
                matches.append((line_number, HIGH_ENTROPY_TOKEN.pattern))
    return matches


def main() -> int:
    problems: list[tuple[Path, int]] = []
    for path in repository_files():
        for line_number, _ in findings(path):
            problems.append((path, line_number))

    if problems:
        print("Possible CFBD credential found. Remove it and rotate the key:")
        for path, line_number in problems:
            print(f"  {path.relative_to(ROOT)}:{line_number}")
        return 1

    print("Secret check passed: no literal CFBD API credentials found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
