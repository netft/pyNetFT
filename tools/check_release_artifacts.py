#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

_PYTHON_TAGS = ("cp310", "cp311", "cp312", "cp313", "cp314")
_PLATFORM_ARCHITECTURES = frozenset(
    {
        ("manylinux2014", "x86_64"),
        ("manylinux2014", "aarch64"),
        ("macosx_11_0", "x86_64"),
        ("macosx_11_0", "arm64"),
    }
)
_PLATFORM_COMPONENTS = {
    tuple(sorted(("manylinux_2_17_x86_64", "manylinux2014_x86_64"))): (
        "manylinux2014",
        "x86_64",
    ),
    tuple(sorted(("manylinux_2_17_aarch64", "manylinux2014_aarch64"))): (
        "manylinux2014",
        "aarch64",
    ),
    ("macosx_11_0_x86_64",): ("macosx_11_0", "x86_64"),
    ("macosx_11_0_arm64",): ("macosx_11_0", "arm64"),
}
_WHEEL_FILENAME = re.compile(
    r"^pynetft-(?P<version>[^-]+)-(?P<python>cp\d+)-(?P<abi>cp\d+)-"
    r"(?P<platform>.+)\.whl$"
)


class ReleaseArtifactError(RuntimeError):
    pass


def validate_inventory(root: Path, version: str) -> None:
    wheels = sorted(root.rglob("*.whl"))
    sdists = sorted(root.rglob("*.tar.gz"))
    if len(sdists) != 1 or sdists[0].name != f"pynetft-{version}.tar.gz":
        raise ReleaseArtifactError("sdist_inventory")

    expected = {
        (python, platform, architecture)
        for python in _PYTHON_TAGS
        for platform, architecture in _PLATFORM_ARCHITECTURES
    }
    actual: set[tuple[str, str, str]] = set()
    for wheel in wheels:
        match = _WHEEL_FILENAME.match(wheel.name)
        if match is None:
            raise ReleaseArtifactError("wheel_filename")
        if match.group("version") != version:
            raise ReleaseArtifactError("wheel_version")
        python = match.group("python")
        if python != match.group("abi"):
            raise ReleaseArtifactError("wheel_abi")
        platform = match.group("platform")
        platform_components = tuple(sorted(platform.split(".")))
        try:
            platform_name, architecture = _PLATFORM_COMPONENTS[platform_components]
        except KeyError:
            raise ReleaseArtifactError("wheel_platform") from None
        entry = (python, platform_name, architecture)
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
