#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

_PYTHON_TAGS = ("cp310", "cp311", "cp312", "cp313", "cp314")
_ARCHITECTURES = ("x86_64", "aarch64")


class ReleaseArtifactError(RuntimeError):
    pass


def validate_inventory(root: Path, version: str) -> None:
    wheels = sorted(root.rglob("*.whl"))
    sdists = sorted(root.rglob("*.tar.gz"))
    if len(sdists) != 1 or sdists[0].name != f"pynetft-{version}.tar.gz":
        raise ReleaseArtifactError("sdist_inventory")

    expected = {
        (python, architecture) for python in _PYTHON_TAGS for architecture in _ARCHITECTURES
    }
    actual: set[tuple[str, str]] = set()
    prefix = re.compile(
        rf"^pynetft-{re.escape(version)}-"
        r"(?P<python>cp3(?:10|11|12|13|14))-(?P=python)-(?P<platform>.+)\.whl$"
    )
    for wheel in wheels:
        match = prefix.match(wheel.name)
        if match is None:
            raise ReleaseArtifactError("wheel_filename")
        python = match.group("python")
        platform = match.group("platform")
        architectures = [
            architecture
            for architecture in _ARCHITECTURES
            if re.search(rf"(?:^|[_.]){re.escape(architecture)}(?:[_.]|$)", platform)
        ]
        if len(architectures) != 1:
            raise ReleaseArtifactError("wheel_architecture")
        architecture = architectures[0]
        if re.search(rf"(?:^|\.)manylinux2014_{re.escape(architecture)}(?:\.|$)", platform) is None:
            raise ReleaseArtifactError("wheel_platform")
        entry = (python, architecture)
        if entry in actual:
            raise ReleaseArtifactError("duplicate_wheel")
        actual.add(entry)
    if actual != expected:
        raise ReleaseArtifactError("wheel_matrix")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    validate_inventory(arguments.root, arguments.version)
    print(f"{len(tuple(arguments.root.rglob('*.whl')))} wheels and one sdist are complete")


if __name__ == "__main__":
    main()
