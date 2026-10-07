from __future__ import annotations

import subprocess
from pathlib import Path

from tools import sync_core


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_sync_removes_files_outside_the_selected_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.name", "Test User")
    git(source, "config", "user.email", "test@example.com")
    for relative_path in sync_core.SELECTED:
        path = source / relative_path
        if relative_path in {"CMakeLists.txt", "LICENSE"}:
            path.write_text(f"{relative_path}\n", encoding="utf-8")
        else:
            path.mkdir()
            (path / "kept.txt").write_text(f"{relative_path}\n", encoding="utf-8")
    git(source, "add", ".")
    git(source, "commit", "-m", "fixture")
    git(source, "tag", "v-test")
    git(source, "remote", "add", "origin", "https://github.com/netft/netft-cpp.git")

    destination = tmp_path / "core"
    destination.mkdir()
    stale = destination / "removed-upstream-path.txt"
    stale.write_text("stale\n", encoding="utf-8")

    sync_core.sync(source, destination, None, candidate=git(source, "rev-parse", "HEAD"))

    assert not stale.exists()
    sync_core.verify(destination)

    assert "tag=unreleased" in (destination / "UPSTREAM").read_text()


def test_snapshot_manifest_order_is_platform_independent(tmp_path: Path) -> None:
    from pathlib import PureWindowsPath

    names = ["cmake/config.in", "UPSTREAM", "LICENSE", "CMakeLists.txt"]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"snapshot\n")
    # Windows Path comparison folds case; a Linux-generated manifest must not.
    assert sorted(map(PureWindowsPath, names)) != sorted(
        map(PureWindowsPath, names), key=lambda path: path.as_posix()
    )
    sync_core.write_manifest(tmp_path)
    recorded = (tmp_path / "SNAPSHOT.sha256").read_text().splitlines()
    assert [line.split("  ", 1)[1] for line in recorded] == sorted(names)
    sync_core.verify(tmp_path)
