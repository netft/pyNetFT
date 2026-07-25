from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load_sdist_checker() -> ModuleType:
    path = ROOT / "tools" / "check_sdist.py"
    assert path.is_file()
    specification = importlib.util.spec_from_file_location("check_sdist", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _build_sdist(destination: Path) -> Path:
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = "1784822400"
    subprocess.run(
        [
            "python",
            "-m",
            "build",
            "--sdist",
            "--no-isolation",
            "--outdir",
            str(destination),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    return next(destination.glob("pynetft-*.tar.gz"))


def test_sdist_excludes_generated_caches_and_is_reproducible(tmp_path: Path) -> None:
    checker = _load_sdist_checker()
    pollution = (
        ROOT / "bindings" / "python" / "__pycache__" / "task10.pyc",
        ROOT / "core" / ".pytest_cache" / "task10",
        ROOT / "src" / "pynetft" / "__pycache__" / "task10.pyc",
    )
    try:
        for path in pollution:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"generated")
        first = _build_sdist(tmp_path / "first")
        checker.validate_sdist(first)
        second = _build_sdist(tmp_path / "second")
        checker.validate_sdist(second)
    finally:
        for path in pollution:
            path.unlink(missing_ok=True)

    assert (
        hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    )
