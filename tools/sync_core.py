#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
        raise SystemExit("core snapshot checksum mismatch")


def sync(source: Path, destination: Path, tag: str) -> None:
    commit = git(source, "rev-parse", f"{tag}^{{commit}}")
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
    sync_parser.add_argument("--tag", required=True)
    subparsers.add_parser("verify")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if arguments.command == "sync":
        sync(arguments.source.resolve(), root / "core", arguments.tag)
    else:
        verify(root / "core")


if __name__ == "__main__":
    main()
