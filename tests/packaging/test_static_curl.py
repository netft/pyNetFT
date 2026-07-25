from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CURL_ARCHIVE_SHA256 = "aa1b66a70eace83dc624508745646c08ae561de512ab403adffb93ac87fc72e6"

WRAPPERS = (
    pytest.param(
        "build_manylinux_curl.sh",
        marks=pytest.mark.skipif(platform.system() != "Linux", reason="Linux-only wrapper"),
    ),
    pytest.param(
        "build_macos_curl.sh",
        marks=pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only wrapper"),
    ),
)


@pytest.mark.curl_build
@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_curl_build_produces_only_the_static_http_library(tmp_path: Path, wrapper: str) -> None:
    if os.environ.get("PYNETFT_RUN_CURL_BUILD_TEST") != "1":
        pytest.skip()

    prefix = tmp_path / "prefix"
    archive = tmp_path / "curl.tar.xz"
    environment = os.environ.copy()
    environment["PYNETFT_CURL_PREFIX"] = str(prefix)
    environment["PYNETFT_CURL_ARCHIVE_CACHE"] = str(archive)
    subprocess.run(
        ["bash", str(ROOT / "tools" / wrapper)],
        check=True,
        env=environment,
    )

    protocols = subprocess.run(
        [str(prefix / "bin" / "curl-config"), "--protocols"],
        check=True,
        capture_output=True,
        text=True,
    )
    version = subprocess.run(
        [str(prefix / "bin" / "curl-config"), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version.stdout.splitlines() == ["libcurl 8.21.0"]
    assert protocols.stdout.splitlines() == ["HTTP"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == CURL_ARCHIVE_SHA256
    assert hashlib.sha256((ROOT / "LICENSES" / "curl.txt").read_bytes()).hexdigest() == (
        "82f2f4427d6545ee5aaac4f0b80428da6cc8ba41c2cf5da3a03680ec327b9681"
    )
    assert (prefix / "lib" / "libcurl.a").is_file()
    assert not tuple((prefix / "lib").glob("libcurl.so*"))
    assert not tuple((prefix / "lib").glob("libcurl*.dylib"))
