#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import re
import subprocess
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath


class WheelValidationError(RuntimeError):
    pass


def _require_exactly_one(members: set[str], pattern: str, description: str) -> str:
    matches = sorted(member for member in members if re.fullmatch(pattern, member))
    if len(matches) != 1:
        raise WheelValidationError(f"expected exactly one {description}, found {len(matches)}")
    return matches[0]


def validate_needed_libraries(libraries: set[str]) -> None:
    libcurl = sorted(
        library for library in libraries if re.fullmatch(r"libcurl\.so(?:\..*)?", library)
    )
    if libcurl:
        raise WheelValidationError(f"native extension dynamically links {', '.join(libcurl)}")


def _needed_libraries(binary: bytes) -> set[str]:
    from elftools.elf.elffile import ELFFile

    dynamic = ELFFile(io.BytesIO(binary)).get_section_by_name(".dynamic")
    if dynamic is None:
        raise WheelValidationError("native extension has no ELF dynamic section")
    return {str(tag.needed) for tag in dynamic.iter_tags() if tag.entry.d_tag == "DT_NEEDED"}


def _contains_directory_pair(parts: tuple[str, ...], parent: str, child: str) -> bool:
    return any(parts[index : index + 2] == (parent, child) for index in range(len(parts) - 1))


def validate_wheel(path: Path, *, self_contained: bool = False) -> None:
    with zipfile.ZipFile(path) as archive:
        member_names = archive.namelist()
        duplicates = sorted(member for member, count in Counter(member_names).items() if count > 1)
        if duplicates:
            raise WheelValidationError(f"duplicate wheel members: {', '.join(duplicates)}")
        members = set(member_names)

        extension = _require_exactly_one(
            members,
            r"pynetft/_native(?:\.[^/]+)?\.so",
            "private native extension",
        )
        if self_contained:
            validate_needed_libraries(_needed_libraries(archive.read(extension)))

    _require_exactly_one(members, r"pynetft/py\.typed", "type marker")
    metadata = _require_exactly_one(
        members,
        r"[^/]+\.dist-info/METADATA",
        "distribution metadata file",
    )
    dist_info = PurePosixPath(metadata).parent.as_posix()
    required = {
        f"{dist_info}/WHEEL",
        f"{dist_info}/licenses/LICENSE",
        f"{dist_info}/licenses/LICENSES/MIT.txt",
        f"{dist_info}/licenses/LICENSES/curl.txt",
        f"{dist_info}/licenses/core/LICENSE",
    }
    missing = sorted(required - members)
    if missing:
        raise WheelValidationError(f"missing required wheel members: {', '.join(missing)}")

    forbidden = []
    for member in members:
        path_parts = PurePosixPath(member).parts
        filename = PurePosixPath(member).name
        installs_cli = filename == "netft" and (
            _contains_directory_pair(path_parts, "bin", "netft") or "scripts" in path_parts
        )
        installs_headers = _contains_directory_pair(
            path_parts, "include", "netft"
        ) or _contains_directory_pair(path_parts, "headers", "netft")
        installs_core_library = filename.startswith("libnetft.so")
        bundles_dynamic_curl = "pynetft.libs" in path_parts and filename.startswith("libcurl")
        if installs_cli or installs_headers or installs_core_library or bundles_dynamic_curl:
            forbidden.append(member)
    if forbidden:
        raise WheelValidationError(f"forbidden wheel members: {', '.join(sorted(forbidden))}")


def _run_auditwheel(path: Path) -> None:
    result = subprocess.run(
        ["auditwheel", "show", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if re.search(r"\blibcurl(?:-[^\s/]*)?\.so(?:\.\d+)*\b", output, flags=re.IGNORECASE):
        raise WheelValidationError(f"auditwheel reported a libcurl dependency for {path}")
    print(result.stdout, end="")


def validate_wheels(wheels: list[Path], *, self_contained: bool, run_auditwheel: bool) -> None:
    if not wheels:
        raise WheelValidationError("no wheels were provided")
    for wheel in wheels:
        if not wheel.is_file():
            raise WheelValidationError(f"wheel does not exist: {wheel}")
        validate_wheel(wheel, self_contained=self_contained)
        if run_auditwheel:
            _run_auditwheel(wheel)
        print(f"{wheel}: wheel structure is valid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-contained",
        action="store_true",
        help="reject a native extension that dynamically links libcurl",
    )
    parser.add_argument(
        "--auditwheel",
        action="store_true",
        help="run auditwheel show separately for every wheel",
    )
    parser.add_argument("wheels", nargs="+", type=Path)
    arguments = parser.parse_args()
    validate_wheels(
        arguments.wheels,
        self_contained=arguments.self_contained,
        run_auditwheel=arguments.auditwheel,
    )


if __name__ == "__main__":
    main()
