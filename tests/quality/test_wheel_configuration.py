from __future__ import annotations

import importlib.util
import shlex
import subprocess
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
    assert "/opt/pynetft-curl/lib/libcurl.a" in linux["environment"]["CMAKE_ARGS"]
    assert "/opt/pynetft-curl/include" in linux["environment"]["CMAKE_ARGS"]


def test_curl_build_script_has_valid_shell_syntax() -> None:
    script = ROOT / "tools" / "build_manylinux_curl.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(script)], check=True)


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
    assert "publish" not in workflow["jobs"]


def test_wheel_checker_accepts_only_the_private_runtime_payload(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "pynetft-2.0.0-cp314-cp314-manylinux2014_x86_64.whl"
    required = (
        "pynetft/__init__.py",
        "pynetft/_native.cpython-314-x86_64-linux-gnu.so",
        "pynetft/py.typed",
        "pynetft-2.0.0.dist-info/METADATA",
        "pynetft-2.0.0.dist-info/WHEEL",
        "pynetft-2.0.0.dist-info/licenses/LICENSE",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.0.dist-info/licenses/core/LICENSE",
    )
    _write_wheel(wheel, members=required)

    checker.validate_wheel(wheel)

    for forbidden in (
        "bin/netft",
        "include/netft/client.hpp",
        "lib/libnetft.so",
        "pynetft-2.0.0.data/scripts/netft",
        "pynetft-2.0.0.data/headers/netft/client.hpp",
    ):
        rejected = tmp_path / f"rejected-{forbidden.replace('/', '-')}.whl"
        _write_wheel(rejected, members=(*required, forbidden))
        with pytest.raises(checker.WheelValidationError):
            checker.validate_wheel(rejected)


def test_wheel_checker_rejects_missing_or_duplicate_native_extensions(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    base = (
        "pynetft/py.typed",
        "pynetft-2.0.0.dist-info/METADATA",
        "pynetft-2.0.0.dist-info/WHEEL",
        "pynetft-2.0.0.dist-info/licenses/LICENSE",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.0.dist-info/licenses/core/LICENSE",
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


def test_wheel_checker_rejects_duplicate_zip_entries(tmp_path: Path) -> None:
    checker = _load_wheel_checker()
    wheel = tmp_path / "duplicate-entry.whl"
    members = (
        "pynetft/_native.cpython-314-x86_64-linux-gnu.so",
        "pynetft/py.typed",
        "pynetft-2.0.0.dist-info/METADATA",
        "pynetft-2.0.0.dist-info/WHEEL",
        "pynetft-2.0.0.dist-info/licenses/LICENSE",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/MIT.txt",
        "pynetft-2.0.0.dist-info/licenses/LICENSES/curl.txt",
        "pynetft-2.0.0.dist-info/licenses/core/LICENSE",
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


def test_auditwheel_inspects_multiple_wheels_individually(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_wheel_checker()
    wheels = [tmp_path / "first.whl", tmp_path / "second.whl"]
    for wheel in wheels:
        wheel.touch()
    validated: list[tuple[Path, bool]] = []
    commands: list[list[str]] = []

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
