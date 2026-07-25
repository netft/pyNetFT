#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath


class SdistValidationError(RuntimeError):
    pass


def validate_sdist(path: Path) -> None:
    with tarfile.open(path, mode="r:gz") as archive:
        file_names = [member.name for member in archive.getmembers() if member.isfile()]

    duplicates = sorted(name for name, count in Counter(file_names).items() if count > 1)
    if duplicates:
        raise SdistValidationError(f"duplicate sdist members: {', '.join(duplicates)}")

    roots = {PurePosixPath(name).parts[0] for name in file_names}
    if len(roots) != 1:
        raise SdistValidationError("sdist must contain exactly one root directory")
    root = roots.pop()
    members = set(file_names)
    required = {
        f"{root}/pyproject.toml",
        f"{root}/CMakeLists.txt",
        f"{root}/README.md",
        f"{root}/CHANGELOG.md",
        f"{root}/CONTRIBUTING.md",
        f"{root}/SECURITY.md",
        f"{root}/docs/api.md",
        f"{root}/docs/migration-2.md",
        f"{root}/LICENSE",
        f"{root}/LICENSES/MIT.txt",
        f"{root}/LICENSES/curl.txt",
        f"{root}/core/LICENSE",
        f"{root}/core/UPSTREAM",
        f"{root}/core/SNAPSHOT.sha256",
        f"{root}/bindings/python/module.cpp",
        f"{root}/src/pynetft/__init__.py",
        f"{root}/src/pynetft/py.typed",
    }
    missing = sorted(required - members)
    if missing:
        raise SdistValidationError(f"missing required sdist members: {', '.join(missing)}")

    forbidden = []
    for name in file_names:
        path_parts = PurePosixPath(name).parts
        if (
            "__pycache__" in path_parts
            or ".pytest_cache" in path_parts
            or PurePosixPath(name).suffix in {".pyc", ".pyo"}
            or PurePosixPath(name).is_absolute()
            or ".." in path_parts
        ):
            forbidden.append(name)
    if forbidden:
        raise SdistValidationError(f"generated or unsafe sdist members: {', '.join(forbidden)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sdists", nargs="+", type=Path)
    arguments = parser.parse_args()
    for sdist in arguments.sdists:
        if not sdist.is_file():
            raise SdistValidationError(f"sdist does not exist: {sdist}")
        validate_sdist(sdist)
        print(f"{sdist}: sdist structure is valid")


if __name__ == "__main__":
    main()
