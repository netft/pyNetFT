#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SELECTED = ("CMakeLists.txt", "LICENSE", "cmake", "include", "src")


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def snapshot_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*") if path.is_file() and path.name != "SNAPSHOT.sha256"
    )


def write_manifest(root: Path) -> None:
    lines = [
        f"{digest(path)}  {path.relative_to(root).as_posix()}" for path in snapshot_files(root)
    ]
    (root / "SNAPSHOT.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(root: Path) -> None:
    expected = (root / "SNAPSHOT.sha256").read_text(encoding="utf-8").splitlines()
    actual = [
        f"{digest(path)}  {path.relative_to(root).as_posix()}" for path in snapshot_files(root)
    ]
    if actual != expected:
        expected_by_path = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in expected}
        actual_by_path = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in actual}
        differences = [
            f"{name}: expected={expected_by_path.get(name, 'missing')} "
            f"actual={actual_by_path.get(name, 'missing')}"
            for name in sorted(expected_by_path.keys() | actual_by_path.keys())
            if expected_by_path.get(name) != actual_by_path.get(name)
        ]
        raise SystemExit("core snapshot checksum mismatch\n" + "\n".join(differences))


def sync(source: Path, destination: Path, tag: str | None, *, candidate: str | None = None) -> None:
    if candidate is not None and not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise SystemExit("candidate must be a full lowercase commit SHA")
    if git(source, "remote", "get-url", "origin") != "https://github.com/netft/netft-cpp.git":
        raise SystemExit("source repository mismatch")
    reference = candidate or tag
    if not reference:
        raise SystemExit("source identity is required")
    commit = git(source, "rev-parse", f"{reference}^{{commit}}")
    if candidate is not None and commit != candidate:
        raise SystemExit("candidate identity mismatch")
    tag = "unreleased" if candidate else tag
    head = git(source, "rev-parse", "HEAD")
    if head != commit:
        raise SystemExit(f"{source} HEAD does not match {tag}")
    if git(source, "status", "--short"):
        raise SystemExit(f"{source} is not clean")

    destination.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-sync-", dir=destination.parent)
    )
    staging = transaction / "snapshot"
    previous = transaction / "previous"
    staging.mkdir()
    try:
        for name in SELECTED:
            origin = source / name
            target = staging / name
            if origin.is_dir():
                shutil.copytree(origin, target)
            else:
                shutil.copy2(origin, target)

        (staging / "UPSTREAM").write_text(
            "\n".join(
                (
                    "repository=https://github.com/netft/netft-cpp",
                    f"tag={tag}",
                    f"commit={commit}",
                    f"paths={','.join(SELECTED)}",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        write_manifest(staging)
        verify(staging)

        if destination.exists():
            destination.rename(previous)
        try:
            staging.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--source", type=Path, required=True)
    identity = sync_parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--tag")
    identity.add_argument("--commit")
    subparsers.add_parser("verify")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if arguments.command == "sync":
        sync(arguments.source.resolve(), root / "core", arguments.tag, candidate=arguments.commit)
    else:
        verify(root / "core")


if __name__ == "__main__":
    main()
