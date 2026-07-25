from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _project_configuration() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def _load_wheel_checker() -> ModuleType:
    path = ROOT / "tools" / "check_wheel.py"
    assert path.is_file()
    specification = importlib.util.spec_from_file_location("check_wheel", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_wheel(path: Path, *, members: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, b"x")


def _valid_wheel_members(extension: str) -> tuple[str, ...]:
    return (
        "pynetft/__init__.py",
        extension,
        "pynetft/py.typed",
        "pynetft-2.0.1.dist-info/METADATA",
        "pynetft-2.0.1.dist-info/WHEEL",
        "pynetft-2.0.1.dist-info/licenses/LICENSE",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.1.dist-info/licenses/core/LICENSE",
    )


def test_cibuildwheel_selects_the_supported_linux_matrix() -> None:
    cibuildwheel = _project_configuration()["tool"]["cibuildwheel"]  # type: ignore[index]
    linux = cibuildwheel["linux"]

    assert cibuildwheel["build"] == [
        "cp310-*",
        "cp311-*",
        "cp312-*",
        "cp313-*",
        "cp314-*",
    ]
    assert cibuildwheel["skip"] == ["*-musllinux_*", "*-manylinux_i686", "pp*", "cp*t-*"]
    assert (
        cibuildwheel["test-command"]
        == "python -m pip check && python -m pytest {project}/tests/artifact -q"
    )
    assert cibuildwheel["test-requires"] == ["pytest"]
    assert linux["archs"] == ["x86_64", "aarch64"]
    assert linux["manylinux-x86_64-image"] == "manylinux2014"
    assert linux["manylinux-aarch64-image"] == "manylinux2014"
    assert linux["before-all"] == "bash {project}/tools/build_manylinux_curl.sh"
    assert "-DCURL_USE_STATIC_LIBS=ON" in linux["environment"]["CMAKE_ARGS"]
    assert "/opt/pynetft-curl/lib/libcurl.a" in linux["environment"]["CMAKE_ARGS"]
    assert "/opt/pynetft-curl/include" in linux["environment"]["CMAKE_ARGS"]


def test_cibuildwheel_configures_separate_native_macos_wheels() -> None:
    macos = _project_configuration()["tool"]["cibuildwheel"]["macos"]  # type: ignore[index]

    assert macos["archs"] == ["x86_64", "arm64"]
    assert macos["before-all"] == "bash {project}/tools/build_macos_curl.sh"
    assert macos["environment"]["MACOSX_DEPLOYMENT_TARGET"] == "11.0"
    assert "-DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=ON" in macos["environment"]["CMAKE_ARGS"]
    assert "-DCURL_USE_STATIC_LIBS=ON" in macos["environment"]["CMAKE_ARGS"]
    assert "/pynetft-curl/lib/libcurl.a" in macos["environment"]["CMAKE_ARGS"]
    assert "/pynetft-curl/include" in macos["environment"]["CMAKE_ARGS"]
    assert "delocate-wheel" in macos["repair-wheel-command"]


@pytest.mark.parametrize(
    "name",
    ("build_static_curl.sh", "build_manylinux_curl.sh", "build_macos_curl.sh"),
)
def test_curl_build_scripts_have_valid_shell_syntax(name: str) -> None:
    script = ROOT / "tools" / name
    assert script.is_file()
    assert script.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_static_curl_build_prefers_shasum_to_incompatible_sha256sum(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sha256sum = bin_dir / "sha256sum"
    fake_sha256sum.write_text(
        "#!/bin/sh\nexit 64\n",
        encoding="utf-8",
    )
    fake_sha256sum.chmod(0o755)
    fake_shasum = bin_dir / "shasum"
    fake_shasum.write_text(
        "#!/bin/sh\n"
        'test "$1" = "-a" || exit 65\n'
        'test "$2" = "256" || exit 66\n'
        'printf "aa1b66a70eace83dc624508745646c08ae561de512ab403adffb93ac87fc72e6  %s\\n" "$3"\n',
        encoding="utf-8",
    )
    fake_shasum.chmod(0o755)
    fake_tar = bin_dir / "tar"
    fake_tar.write_text(
        "#!/bin/sh\n"
        'while test "$1" != "-C"; do shift; done\n'
        "shift\n"
        'mkdir -p "$1"\n'
        "printf '#!/bin/sh\\nexit 0\\n' > \"$1/configure\"\n"
        'chmod +x "$1/configure"\n',
        encoding="utf-8",
    )
    fake_tar.chmod(0o755)
    fake_make = bin_dir / "make"
    fake_make.write_text(
        "#!/bin/sh\n"
        'if test "${1:-}" = "install"; then\n'
        '  mkdir -p "$PYNETFT_CURL_PREFIX/bin" "$PYNETFT_CURL_PREFIX/lib"\n'
        '  : > "$PYNETFT_CURL_PREFIX/lib/libcurl.a"\n'
        "  printf '#!/bin/sh\\n"
        'case "$1" in\\n'
        '  --version) echo "libcurl 8.21.0" ;;\\n'
        "  --protocols) echo HTTP ;;\\n"
        "esac\\n"
        '\' > "$PYNETFT_CURL_PREFIX/bin/curl-config"\n'
        '  chmod +x "$PYNETFT_CURL_PREFIX/bin/curl-config"\n'
        "fi\n",
        encoding="utf-8",
    )
    fake_make.chmod(0o755)
    prefix = tmp_path / "prefix"
    archive = tmp_path / "curl.tar.xz"
    archive.write_bytes(b"controlled archive")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "PYNETFT_CURL_PREFIX": str(prefix),
            "PYNETFT_CURL_ARCHIVE_CACHE": str(archive),
        }
    )

    subprocess.run(
        ["/bin/bash", str(ROOT / "tools" / "build_static_curl.sh")],
        check=True,
        env=environment,
    )

    assert (prefix / "lib" / "libcurl.a").is_file()


@pytest.mark.parametrize("name", ("build_manylinux_curl.sh", "build_macos_curl.sh"))
def test_curl_build_wrappers_forward_the_build_environment(tmp_path: Path, name: str) -> None:
    prefix = tmp_path / "prefix"
    archive = tmp_path / "curl.tar.xz"
    capture = tmp_path / "capture"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_bash = bin_dir / "bash"
    fake_bash.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n%s\\n%s\\n' \\\n"
        '  "$PYNETFT_CURL_PREFIX" \\\n'
        '  "$PYNETFT_CURL_ARCHIVE_CACHE" \\\n'
        '  "$1" > "$PYNETFT_CAPTURE"\n',
        encoding="utf-8",
    )
    fake_bash.chmod(0o755)
    fake_mktemp = bin_dir / "mktemp"
    fake_mktemp.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_mktemp.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "PYNETFT_CAPTURE": str(capture),
            "PYNETFT_CURL_PREFIX": str(prefix),
            "PYNETFT_CURL_ARCHIVE_CACHE": str(archive),
        }
    )

    subprocess.run(["/bin/bash", str(ROOT / "tools" / name)], check=True, env=environment)

    forwarded_prefix, forwarded_archive, implementation = capture.read_text(
        encoding="utf-8"
    ).splitlines()
    assert forwarded_prefix == str(prefix)
    assert forwarded_archive == str(archive)
    assert Path(implementation).resolve() == ROOT / "tools" / "build_static_curl.sh"


def test_wheel_workflow_has_smoke_and_full_build_modes() -> None:
    with (ROOT / ".github" / "workflows" / "wheels.yml").open(encoding="utf-8") as stream:
        workflow = yaml.load(stream, Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    curl_build = workflow["jobs"]["curl-build"]
    curl_test = next(
        step for step in curl_build["steps"] if "PYNETFT_RUN_CURL_BUILD_TEST" in step.get("env", {})
    )
    assert curl_test["env"]["PYNETFT_RUN_CURL_BUILD_TEST"] == "1"
    curl_command = shlex.split(curl_test["run"])
    assert curl_command[:3] == ["python", "-m", "pytest"]
    assert (ROOT / curl_command[3]).is_file()

    smoke = workflow["jobs"]["smoke"]
    assert smoke["if"] == "github.event_name == 'pull_request'"
    assert smoke["needs"] == "curl-build"
    assert smoke["runs-on"] == "ubuntu-24.04"
    smoke_install = next(
        step for step in smoke["steps"] if step.get("name") == "Install wheel build frontend"
    )
    assert "cibuildwheel==3.4.1" in smoke_install["run"]
    assert "auditwheel" in smoke_install["run"]
    smoke_build = next(
        step for step in smoke["steps"] if step.get("run", "").startswith("python -m cibuildwheel")
    )
    assert smoke_build["env"]["CIBW_BUILD"] == "cp310-*"
    assert smoke_build["env"]["CIBW_ARCHS_LINUX"] == "x86_64"

    full = workflow["jobs"]["wheels"]
    assert full["if"] == "github.event_name != 'pull_request'"
    assert full["needs"] == "curl-build"
    full_install = next(
        step for step in full["steps"] if step.get("name") == "Install wheel build frontend"
    )
    assert "cibuildwheel==3.4.1" in full_install["run"]
    assert "auditwheel" in full_install["run"]
    matrix = full["strategy"]["matrix"]["include"]
    assert {entry["arch"] for entry in matrix} == {"x86_64", "aarch64"}
    assert all(entry["runner"] for entry in matrix)

    build_step = next(
        step for step in full["steps"] if step.get("run", "").startswith("python -m cibuildwheel")
    )
    assert build_step["env"]["CIBW_ARCHS_LINUX"] == "${{ matrix.arch }}"
    validation_step = next(
        step
        for step in full["steps"]
        if step.get("name") == "Validate wheel structure and dependencies"
    )
    expected_validation = [
        "python",
        "tools/check_wheel.py",
        "--self-contained",
        "--auditwheel",
        "wheelhouse/*.whl",
    ]
    assert shlex.split(validation_step["run"]) == expected_validation
    smoke_validation = next(
        step
        for step in smoke["steps"]
        if step.get("name") == "Validate wheel structure and dependencies"
    )
    assert shlex.split(smoke_validation["run"]) == expected_validation

    macos_matrix = {
        "x86_64": "macos-15-intel",
        "arm64": "macos-15",
    }
    expected_macos_validation = [
        "python",
        "tools/check_wheel.py",
        "--self-contained",
        "--delocate",
        "wheelhouse/*.whl",
    ]
    for name, event_condition, artifact_name, build_override in (
        (
            "macos-smoke",
            "github.event_name == 'pull_request'",
            "wheels-smoke-macos-${{ matrix.arch }}",
            "cp310-*",
        ),
        (
            "macos-wheels",
            "github.event_name != 'pull_request'",
            "wheels-macos-${{ matrix.arch }}",
            None,
        ),
    ):
        macos = workflow["jobs"][name]
        assert macos["if"] == event_condition
        assert macos["needs"] == "curl-build"
        assert macos["runs-on"] == "${{ matrix.runner }}"
        assert macos["strategy"]["fail-fast"] == "false"
        assert {
            entry["arch"]: entry["runner"] for entry in macos["strategy"]["matrix"]["include"]
        } == macos_matrix

        macos_install = next(
            step for step in macos["steps"] if "cibuildwheel==3.4.1" in step.get("run", "")
        )
        assert "cibuildwheel==3.4.1" in macos_install["run"]
        assert "delocate" in macos_install["run"]
        macos_build = next(
            step
            for step in macos["steps"]
            if step.get("run", "").startswith("python -m cibuildwheel")
        )
        assert macos_build["env"]["CIBW_ARCHS_MACOS"] == "${{ matrix.arch }}"
        assert macos_build["env"].get("CIBW_BUILD") == build_override
        assert shlex.split(macos_build["run"]) == [
            "python",
            "-m",
            "cibuildwheel",
            "--platform",
            "macos",
            "--output-dir",
            "wheelhouse",
        ]
        macos_validation = next(
            step for step in macos["steps"] if "tools/check_wheel.py" in step.get("run", "")
        )
        assert shlex.split(macos_validation["run"]) == expected_macos_validation
        macos_upload = next(
            step for step in macos["steps"] if step.get("uses") == "actions/upload-artifact@v6"
        )
        assert macos_upload["with"]["name"] == artifact_name
        assert macos_upload["with"]["path"] == "wheelhouse/*.whl"
        assert macos_upload["with"]["if-no-files-found"] == "error"

    assert "publish" not in workflow["jobs"]


def test_wheel_checker_accepts_only_the_private_runtime_payload(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp314-cp314-manylinux2014_x86_64.whl"
    required = (
        "pynetft/__init__.py",
        "pynetft/_native.cpython-314-x86_64-linux-gnu.so",
        "pynetft/py.typed",
        "pynetft-2.0.1.dist-info/METADATA",
        "pynetft-2.0.1.dist-info/WHEEL",
        "pynetft-2.0.1.dist-info/licenses/LICENSE",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.1.dist-info/licenses/core/LICENSE",
    )
    _write_wheel(wheel, members=required)

    checker.validate_wheel(wheel)

    for forbidden in (
        "bin/netft",
        "include/netft/client.hpp",
        "lib/libnetft.so",
        "pynetft-2.0.1.data/scripts/netft",
        "pynetft-2.0.1.data/headers/netft/client.hpp",
    ):
        rejected = tmp_path / f"rejected-{forbidden.replace('/', '-')}.whl"
        _write_wheel(rejected, members=(*required, forbidden))
        with pytest.raises(checker.WheelValidationError):
            checker.validate_wheel(rejected)


def test_wheel_checker_rejects_missing_or_duplicate_native_extensions(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    base = (
        "pynetft/py.typed",
        "pynetft-2.0.1.dist-info/METADATA",
        "pynetft-2.0.1.dist-info/WHEEL",
        "pynetft-2.0.1.dist-info/licenses/LICENSE",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.1.dist-info/licenses/core/LICENSE",
    )
    no_extension = tmp_path / "no-extension.whl"
    _write_wheel(no_extension, members=base)
    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheel(no_extension)

    duplicate = tmp_path / "duplicate-extension.whl"
    _write_wheel(
        duplicate,
        members=(
            *base,
            "pynetft/_native.cpython-314-x86_64-linux-gnu.so",
            "pynetft/_native.abi3.so",
        ),
    )
    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheel(duplicate)


@pytest.mark.parametrize(
    "license_member",
    (
        "pynetft-2.0.1.dist-info/licenses/LICENSE",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.1.dist-info/licenses/core/LICENSE",
    ),
)
def test_wheel_checker_rejects_each_missing_license(tmp_path: Path, license_member: str) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp314-cp314-linux_x86_64.whl"
    members = _valid_wheel_members("pynetft/_native.cpython-314-x86_64-linux-gnu.so")
    _write_wheel(wheel, members=tuple(member for member in members if member != license_member))

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheel(wheel)


def test_wheel_checker_rejects_duplicate_zip_entries(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "duplicate-entry.whl"
    members = (
        "pynetft/_native.cpython-314-x86_64-linux-gnu.so",
        "pynetft/py.typed",
        "pynetft-2.0.1.dist-info/METADATA",
        "pynetft-2.0.1.dist-info/WHEEL",
        "pynetft-2.0.1.dist-info/licenses/LICENSE",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.1.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.1.dist-info/licenses/core/LICENSE",
    )
    with pytest.warns(UserWarning), zipfile.ZipFile(wheel, "w") as archive:
        for member in (*members, "pynetft/py.typed"):
            archive.writestr(member, b"x")

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheel(wheel)


def test_wheel_checker_rejects_a_dynamic_libcurl_dependency() -> None:
    checker = _load_wheel_checker()

    checker.validate_needed_libraries({"libc.so.6", "libpthread.so.0"})
    with pytest.raises(checker.WheelValidationError):
        checker.validate_needed_libraries({"libc.so.6", "libcurl.so.4"})


def test_self_containment_dispatches_elf_inspection_for_linux_wheels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp314-cp314-manylinux2014_x86_64.whl"
    _write_wheel(
        wheel,
        members=_valid_wheel_members("pynetft/_native.cpython-314-x86_64-linux-gnu.so"),
    )
    inspected: list[bytes] = []

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        checker,
        "_needed_libraries",
        lambda binary: inspected.append(binary) or {"libc.so.6"},
    )

    checker.validate_wheel(wheel, self_contained=True)

    assert inspected == [b"x"]


def test_self_containment_extracts_and_inspects_macos_extensions_with_otool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp314-cp314-macosx_11_0_arm64.whl"
    _write_wheel(
        wheel,
        members=_valid_wheel_members("pynetft/_native.cpython-314-darwin.so"),
    )
    commands: list[list[str]] = []

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        checker,
        "_needed_libraries",
        lambda binary: pytest.fail(f"ELF inspection received {binary!r}"),
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        extension = Path(command[-1])
        assert extension.is_file()
        assert extension.read_bytes() == b"x"
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{extension}:\n\t/usr/lib/libSystem.B.dylib\n",
            stderr="",
        )

    monkeypatch.setattr(checker.subprocess, "run", run)

    checker.validate_wheel(wheel, self_contained=True)

    assert len(commands) == 1
    assert commands[0][:2] == ["otool", "-L"]


@pytest.mark.parametrize(
    "dependency",
    (
        "@rpath/libcurl.dylib",
        "/opt/homebrew/opt/curl/lib/libcurl.4.dylib",
        "/usr/local/lib/libexample.dylib",
        "/opt/local/lib/libexample.dylib",
        "/srv/pynetft/lib/libexample.dylib",
    ),
)
def test_macos_dependency_validation_rejects_external_native_libraries(dependency: str) -> None:
    checker = _load_wheel_checker()

    with pytest.raises(checker.WheelValidationError):
        checker.validate_macos_dependencies({dependency})


def test_macos_dependency_validation_accepts_apple_system_libraries() -> None:
    checker = _load_wheel_checker()

    checker.validate_macos_dependencies(
        {
            "/usr/lib/libSystem.B.dylib",
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
        }
    )


def test_macos_self_containment_rejects_an_otool_package_manager_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp314-cp314-macosx_11_0_x86_64.whl"
    _write_wheel(
        wheel,
        members=_valid_wheel_members("pynetft/_native.cpython-314-darwin.so"),
    )
    monkeypatch.setattr(sys, "platform", "darwin")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{command[-1]}:\n\t/opt/homebrew/lib/libexample.dylib\n",
            stderr="",
        )

    monkeypatch.setattr(checker.subprocess, "run", run)

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheel(wheel, self_contained=True)


@pytest.mark.parametrize(
    ("host", "wheel_name", "message"),
    (
        ("darwin", "pynetft-2.0.1-cp314-cp314-manylinux2014_x86_64.whl", "Linux"),
        ("linux", "pynetft-2.0.1-cp314-cp314-macosx_11_0_arm64.whl", "macOS"),
    ),
)
def test_native_inspection_rejects_the_wrong_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
    wheel_name: str,
    message: str,
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / wheel_name
    extension = (
        "pynetft/_native.cpython-314-darwin.so"
        if "macosx" in wheel_name
        else "pynetft/_native.cpython-314-x86_64-linux-gnu.so"
    )
    _write_wheel(wheel, members=_valid_wheel_members(extension))
    monkeypatch.setattr(sys, "platform", host)

    with pytest.raises(checker.WheelValidationError, match=message):
        checker.validate_wheel(wheel, self_contained=True)


def test_auditwheel_inspects_multiple_wheels_individually(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheels = [
        tmp_path / "pynetft-2.0.1-cp310-cp310-manylinux2014_x86_64.whl",
        tmp_path / "pynetft-2.0.1-cp311-cp311-manylinux2014_aarch64.whl",
    ]
    for wheel in wheels:
        wheel.touch()
    validated: list[tuple[Path, bool]] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(sys, "platform", "linux")

    monkeypatch.setattr(
        checker,
        "validate_wheel",
        lambda path, *, self_contained: validated.append((path, self_contained)),
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="compatible", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", run)

    checker.validate_wheels(wheels, self_contained=True, run_auditwheel=True)

    assert validated == [(wheel, True) for wheel in wheels]
    assert commands == [["auditwheel", "show", str(wheel)] for wheel in wheels]


def test_delocate_inspects_multiple_macos_wheels_individually(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheels = [
        tmp_path / "pynetft-2.0.1-cp310-cp310-macosx_11_0_x86_64.whl",
        tmp_path / "pynetft-2.0.1-cp310-cp310-macosx_11_0_arm64.whl",
    ]
    for wheel in wheels:
        wheel.touch()
    validated: list[tuple[Path, bool]] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(sys, "platform", "darwin")

    monkeypatch.setattr(
        checker,
        "validate_wheel",
        lambda path, *, self_contained: validated.append((path, self_contained)),
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout="/usr/lib/libSystem.B.dylib", stderr=""
        )

    monkeypatch.setattr(checker.subprocess, "run", run)

    checker.validate_wheels(
        wheels,
        self_contained=True,
        run_auditwheel=False,
        run_delocate=True,
    )

    assert validated == [(wheel, True) for wheel in wheels]
    assert commands == [["delocate-listdeps", "--all", str(wheel)] for wheel in wheels]


def test_delocate_rejects_an_external_curl_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp310-cp310-macosx_11_0_arm64.whl"
    wheel.touch()
    monkeypatch.setattr(checker, "validate_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "platform", "darwin")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 0, stdout="@rpath/libcurl.4.dylib", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", run)

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheels(
            [wheel],
            self_contained=False,
            run_auditwheel=False,
            run_delocate=True,
        )


@pytest.mark.parametrize(
    ("wheel_name", "run_auditwheel", "run_delocate"),
    (
        ("pynetft-2.0.1-cp310-cp310-macosx_11_0_arm64.whl", True, False),
        ("pynetft-2.0.1-cp310-cp310-manylinux2014_x86_64.whl", False, True),
    ),
)
def test_platform_specific_external_inspection_rejects_other_wheel_tags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    wheel_name: str,
    run_auditwheel: bool,
    run_delocate: bool,
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / wheel_name
    wheel.touch()
    monkeypatch.setattr(checker, "validate_wheel", lambda *args, **kwargs: None)

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheels(
            [wheel],
            self_contained=False,
            run_auditwheel=run_auditwheel,
            run_delocate=run_delocate,
        )


def test_auditwheel_rejects_a_linux_wheel_on_a_non_linux_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp310-cp310-manylinux2014_x86_64.whl"
    wheel.touch()
    monkeypatch.setattr(checker, "validate_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("auditwheel reached subprocess execution"),
    )

    with pytest.raises(checker.WheelValidationError, match="auditwheel.*Linux host"):
        checker.validate_wheels(
            [wheel],
            self_contained=False,
            run_auditwheel=True,
            run_delocate=False,
        )


def test_delocate_rejects_a_macos_wheel_on_a_non_macos_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.1-cp310-cp310-macosx_11_0_arm64.whl"
    wheel.touch()
    monkeypatch.setattr(checker, "validate_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("delocate reached subprocess execution"),
    )

    with pytest.raises(checker.WheelValidationError, match="delocate.*macOS host"):
        checker.validate_wheels(
            [wheel],
            self_contained=False,
            run_auditwheel=False,
            run_delocate=True,
        )


def test_wheel_checker_rejects_an_empty_artifact_set() -> None:
    checker = _load_wheel_checker()

    with pytest.raises(checker.WheelValidationError):
        checker.validate_wheels([], self_contained=True, run_auditwheel=True)


def test_wheel_checker_rejects_libcurl_reported_by_auditwheel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "reported.whl"
    wheel.touch()

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="external library: libcurl.so.4",
            stderr="",
        )

    monkeypatch.setattr(checker.subprocess, "run", run)
    with pytest.raises(checker.WheelValidationError):
        checker._run_auditwheel(wheel)
