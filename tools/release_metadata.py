#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

import tomllib


class ReleaseMetadataError(RuntimeError):
    pass


class ReleaseMetadata(NamedTuple):
    version: str
    tag: str
    release_date: date


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    return str(project["project"]["version"])


def _cmake_version(root: Path) -> str:
    content = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    match = re.search(
        r"^project\(pynetft VERSION ([0-9]+\.[0-9]+\.[0-9]+) LANGUAGES CXX\)$",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ReleaseMetadataError("cmake_version")
    return match.group(1)


def _changelog_releases(path: Path) -> dict[str, date]:
    releases: dict[str, date] = {}
    pattern = re.compile(
        r"^## ([0-9]+\.[0-9]+\.[0-9]+) - ([0-9]{4}-[0-9]{2}-[0-9]{2})$",
        re.MULTILINE,
    )
    for match in pattern.finditer(path.read_text(encoding="utf-8")):
        releases[match.group(1)] = date.fromisoformat(match.group(2))
    return releases


def validate_release(root: Path, tag: str) -> ReleaseMetadata:
    version = _project_version(root)
    if tag != f"v{version}":
        raise ReleaseMetadataError("tag_version")
    if _cmake_version(root) != version:
        raise ReleaseMetadataError("cmake_version")
    releases = _changelog_releases(root / "CHANGELOG.md")
    if version not in releases:
        raise ReleaseMetadataError("changelog_version")
    return ReleaseMetadata(version, tag, releases[version])


def changelog_notes(path: Path, version: str) -> str:
    content = path.read_text(encoding="utf-8")
    heading = re.compile(
        rf"^## {re.escape(version)} - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\n",
        re.MULTILINE,
    )
    match = heading.search(content)
    if match is None:
        raise ReleaseMetadataError("changelog_version")
    next_heading = re.search(r"^## ", content[match.end() :], re.MULTILINE)
    end = len(content) if next_heading is None else match.end() + next_heading.start()
    notes = content[match.end() : end].strip()
    if not notes:
        raise ReleaseMetadataError("changelog_notes")
    return notes + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "notes"))
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if arguments.command == "validate":
        if arguments.tag is None:
            raise SystemExit("--tag is required")
        validate_release(root, arguments.tag)
        return
    metadata = validate_release(root, arguments.tag or f"v{_project_version(root)}")
    notes = changelog_notes(root / "CHANGELOG.md", metadata.version)
    if arguments.output is None:
        print(notes, end="")
    else:
        arguments.output.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
