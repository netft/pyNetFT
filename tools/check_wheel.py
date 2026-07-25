#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tempfile
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


def validate_macos_dependencies(dependencies: set[str]) -> None:
    dynamic_curl = []
    external = []
    for dependency in sorted(dependencies):
        library_name = PurePosixPath(dependency).name
        if re.fullmatch(
            r"libcurl(?:\.\d+)*(?:\.dylib|\.so(?:\.\d+)*)",
            library_name,
            flags=re.IGNORECASE,
        ):
            dynamic_curl.append(dependency)
        if dependency.startswith("/") and not dependency.startswith(
            ("/usr/lib/", "/System/Library/")
        ):
            external.append(dependency)
    if dynamic_curl:
        raise WheelValidationError(f"native extension dynamically links {', '.join(dynamic_curl)}")
    if external:
        raise WheelValidationError(
            f"native extension has non-system dependencies: {', '.join(external)}"
        )


def _needed_libraries(binary: bytes) -> set[str]:
    from elftools.elf.elffile import ELFFile

    dynamic = ELFFile(io.BytesIO(binary)).get_section_by_name(".dynamic")
    if dynamic is None:
        raise WheelValidationError("native extension has no ELF dynamic section")
    return {str(tag.needed) for tag in dynamic.iter_tags() if tag.entry.d_tag == "DT_NEEDED"}


def _wheel_platform(path: Path) -> str:
    filename = path.name
    if not filename.endswith(".whl"):
        raise WheelValidationError(f"not a wheel filename: {path}")
    components = filename[:-4].rsplit("-", 3)
    if len(components) != 4:
        raise WheelValidationError(f"wheel filename has no platform tag: {path}")
    platform_tags = components[-1].split(".")
    is_linux = any(tag.startswith(("linux_", "manylinux", "musllinux")) for tag in platform_tags)
    is_macos = any(tag.startswith("macosx_") for tag in platform_tags)
    if is_linux == is_macos:
        raise WheelValidationError(f"unsupported wheel platform tag in {path}")
    return "linux" if is_linux else "macos"


def _dependencies_from_tool_output(output: str) -> set[str]:
    dependencies = set()
    for line in output.splitlines():
        dependency = line.strip().split(" (", maxsplit=1)[0]
        if dependency and not dependency.endswith(":"):
            dependencies.add(dependency)
    return dependencies


def _inspect_macos_extension(archive: zipfile.ZipFile, extension: str) -> None:
    with tempfile.TemporaryDirectory(prefix="pynetft-wheel-") as directory:
        extension_path = Path(archive.extract(extension, directory))
        result = subprocess.run(
            ["otool", "-L", str(extension_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    validate_macos_dependencies(_dependencies_from_tool_output(f"{result.stdout}\n{result.stderr}"))


def _validate_native_dependencies(
    path: Path,
    archive: zipfile.ZipFile,
    extension: str,
) -> None:
    platform = _wheel_platform(path)
    if platform == "linux":
        if not sys.platform.startswith("linux"):
            raise WheelValidationError(
                f"native inspection for Linux wheel requires a Linux host: {path}"
            )
        validate_needed_libraries(_needed_libraries(archive.read(extension)))
        return
    if sys.platform != "darwin":
        raise WheelValidationError(
            f"native inspection for macOS wheel requires a macOS host: {path}"
        )
    _inspect_macos_extension(archive, extension)


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
            _validate_native_dependencies(path, archive, extension)

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


def _run_delocate(path: Path) -> None:
    result = subprocess.run(
        ["delocate-listdeps", "--all", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    validate_macos_dependencies(_dependencies_from_tool_output(f"{result.stdout}\n{result.stderr}"))
    print(result.stdout, end="")


def validate_wheels(
    wheels: list[Path],
    *,
    self_contained: bool,
    run_auditwheel: bool,
    run_delocate: bool = False,
) -> None:
    if not wheels:
        raise WheelValidationError("no wheels were provided")
    for wheel in wheels:
        if not wheel.is_file():
            raise WheelValidationError(f"wheel does not exist: {wheel}")
        validate_wheel(wheel, self_contained=self_contained)
        if run_auditwheel:
            if _wheel_platform(wheel) != "linux":
                raise WheelValidationError(f"auditwheel cannot inspect a non-Linux wheel: {wheel}")
            if not sys.platform.startswith("linux"):
                raise WheelValidationError(f"auditwheel inspection requires a Linux host: {wheel}")
            _run_auditwheel(wheel)
        if run_delocate:
            if _wheel_platform(wheel) != "macos":
                raise WheelValidationError(f"delocate cannot inspect a non-macOS wheel: {wheel}")
            if sys.platform != "darwin":
                raise WheelValidationError(f"delocate inspection requires a macOS host: {wheel}")
            _run_delocate(wheel)
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
    parser.add_argument(
        "--delocate",
        action="store_true",
        help="run delocate-listdeps separately for every macOS wheel",
    )
    parser.add_argument("wheels", nargs="+", type=Path)
    arguments = parser.parse_args()
    validate_wheels(
        arguments.wheels,
        self_contained=arguments.self_contained,
        run_auditwheel=arguments.auditwheel,
        run_delocate=arguments.delocate,
    )


if __name__ == "__main__":
    main()
