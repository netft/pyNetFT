from __future__ import annotations

from enum import Enum
from operator import index
from pathlib import Path
from re import search
from subprocess import run
from sys import executable

import pytest
import tomllib
import yaml
from mypy import api as mypy_api

from pynetft import _native

ROOT = Path(__file__).parents[2]
NATIVE_ENUM_TYPES = (
    _native.ForceUnit,
    _native.TorqueUnit,
    _native.CalibrationSource,
    _native.RecoveryPolicy,
    _native.ClientState,
    _native.FaultCode,
    _native.StatusSeverity,
    _native.ReadStatus,
)


def _run_mypy(*arguments: str) -> tuple[str, str, int]:
    return mypy_api.run(
        [
            "--no-incremental",
            "--no-site-packages",
            *arguments,
        ]
    )


def test_configured_mypy_finds_src_package_without_installation() -> None:
    stdout, stderr, status = _run_mypy()

    assert status == 0, stdout + stderr


def test_native_stub_accepts_mutable_fields() -> None:
    fixture = ROOT / "tests/typecheck/native_mutable.py"
    stdout, stderr, status = _run_mypy(
        "--config-file=tests/typecheck/mypy.ini",
        str(fixture),
    )

    assert status == 0, stdout + stderr


def test_native_stub_accepts_runtime_enum_and_sample_container_behavior() -> None:
    fixture = ROOT / "tests/typecheck/native_runtime.py"
    stdout, stderr, status = _run_mypy(
        "--config-file=tests/typecheck/mypy.ini",
        str(fixture),
    )

    assert status == 0, stdout + stderr


def test_native_stub_rejects_readonly_fields_and_enum_iteration() -> None:
    fixture = ROOT / "tests/typecheck/native_rejected.py"
    stdout, stderr, status = _run_mypy(
        "--config-file=tests/typecheck/mypy.ini",
        "--show-error-codes",
        str(fixture),
    )
    errors = [line for line in stdout.splitlines() if ": error:" in line]

    assert status == 1, stdout + stderr
    assert len(errors) == 4
    assert sum("[misc]" in error for error in errors) == 3
    assert sum("[attr-defined]" in error for error in errors) == 1


@pytest.mark.parametrize("enum_type", NATIVE_ENUM_TYPES)
def test_native_enum_runtime_is_not_iterable_enum_class(enum_type: type[object]) -> None:
    assert not issubclass(enum_type, Enum)
    with pytest.raises(TypeError):
        iter(enum_type)


@pytest.mark.parametrize("enum_type", NATIVE_ENUM_TYPES)
def test_native_enum_runtime_supports_pybind_integer_protocol(
    enum_type: type[object],
) -> None:
    members = enum_type.__members__  # type: ignore[attr-defined]
    assert isinstance(members, dict)
    first = next(iter(members.values()))

    assert enum_type(first.value) == first  # type: ignore[attr-defined,call-arg]
    assert enum_type(first) == first  # type: ignore[call-arg]
    assert int(first) == first.value  # type: ignore[arg-type,attr-defined]
    assert index(first) == first.value  # type: ignore[arg-type,attr-defined]


def test_native_sample_vector_properties_are_lists() -> None:
    sample = _native.Sample()

    assert isinstance(sample.raw_wrench, list)
    assert isinstance(sample.force, list)
    assert isinstance(sample.torque, list)


@pytest.mark.parametrize(
    ("value", "attributes"),
    [
        (
            _native.Sample(),
            (
                "rdt_sequence",
                "ft_sequence",
                "status",
                "raw_wrench",
                "force",
                "torque",
                "force_unit",
                "torque_unit",
                "configuration_revision",
                "received_at_ns",
            ),
        ),
        (
            _native.Health(),
            (
                "state",
                "fault_code",
                "sensor_host",
                "rdt_port",
                "sensor_configuration",
                "last_rdt_sequence",
                "last_ft_sequence",
                "last_status",
                "receive_rate_hz",
                "delivery_rate_hz",
                "received_count",
                "delivered_count",
                "rate_limited_count",
                "device_error_count",
                "warning_count",
                "lost_count",
                "duplicate_count",
                "out_of_order_count",
                "malformed_count",
                "reconnect_count",
                "timeout_count",
                "callback_error_count",
                "ft_stall_count",
                "ft_backward_count",
                "ft_restart_count",
                "calibration_change_count",
                "last_record_age",
                "last_error",
                "last_ft_progress",
            ),
        ),
        (_native.ReadResult(), ("status", "sample")),
    ],
)
def test_native_readonly_runtime_fields_reject_assignment(
    value: object, attributes: tuple[str, ...]
) -> None:
    for attribute in attributes:
        with pytest.raises(AttributeError):
            setattr(value, attribute, getattr(value, attribute))


def test_sanitizer_shell_is_fail_fast() -> None:
    with (ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    sanitizer_steps = workflow["jobs"]["sanitizers"]["steps"]
    test_step = next(
        step
        for step in sanitizer_steps
        if step.get("name") == "Test native queue and extension integration"
    )

    script = test_step["run"].lstrip()
    assert script.startswith("pixi run bash -euo pipefail -c")
    assert "detect_leaks=0" not in script
    assert "PYTHONMALLOC=malloc" in script
    assert "tools/lsan.supp" in script


def test_bash_fail_fast_rejects_a_failed_first_command() -> None:
    completed = run(
        ["bash", "-euo", "pipefail", "-c", "false; true"],
        check=False,
    )

    assert completed.returncode != 0


def test_python_matrix_selects_runtime_tests_only() -> None:
    with (ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    python_steps = workflow["jobs"]["python"]["steps"]
    test_step = next(
        step
        for step in python_steps
        if step.get("name") == "Run Python and fake-sensor integration tests"
    )

    assert test_step["run"] == "python -m pytest -q tests/python tests/integration"


def test_quality_environment_checks_conda_executable_dependencies() -> None:
    with (ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    quality_steps = workflow["jobs"]["quality"]["steps"]
    commands = {step["run"] for step in quality_steps if isinstance(step.get("run"), str)}

    assert "pixi run patchelf --version" in commands
    assert "pixi run python -m cibuildwheel --help" in commands
    assert "pixi run python -m pip check" not in commands


def test_pixi_workspace_resolves_native_linux_and_macos_platforms() -> None:
    with (ROOT / "pixi.toml").open("rb") as stream:
        manifest = tomllib.load(stream)

    assert set(manifest["workspace"]["platforms"]) == {
        "linux-64",
        "linux-aarch64",
        "osx-64",
        "osx-arm64",
    }


def test_python_build_backend_matches_pixi_environment() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    with (ROOT / "pixi.toml").open("rb") as stream:
        pixi = tomllib.load(stream)

    for dependency in ("scikit-build-core", "pybind11"):
        backend_requirement = next(
            requirement
            for requirement in project["build-system"]["requires"]
            if requirement.startswith(dependency)
        )
        assert backend_requirement.removeprefix(dependency) == pixi["dependencies"][dependency]
    assert project["tool"]["scikit-build"]["minimum-version"] == "build-system.requires"


def test_macos_pixi_targets_provide_native_wheel_repair_tools() -> None:
    with (ROOT / "pixi.toml").open("rb") as stream:
        manifest = tomllib.load(stream)

    default_dependencies = manifest["dependencies"]
    target_dependencies = manifest["target"]

    assert "auditwheel" not in default_dependencies
    for platform in ("linux-64", "linux-aarch64"):
        assert "auditwheel" in target_dependencies[platform]["dependencies"]
    for platform in ("osx-64", "osx-arm64"):
        dependencies = target_dependencies[platform]["dependencies"]
        assert dependencies["cibuildwheel"] == "==3.4.1"
        assert "delocate" in dependencies
        assert "auditwheel" not in dependencies


def test_macos_ci_runs_native_and_fake_sensor_tests_on_both_architectures() -> None:
    with (ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    macos = workflow["jobs"]["macos"]
    matrix = macos["strategy"]["matrix"]
    commands = [step["run"] for step in macos["steps"] if isinstance(step.get("run"), str)]

    assert macos["runs-on"] == "${{ matrix.runner }}"
    assert macos["strategy"]["fail-fast"] is False
    assert {(entry["runner"], entry["arch"]) for entry in matrix["include"]} == {
        ("macos-15-intel", "x86_64"),
        ("macos-15", "arm64"),
    }
    assert any(
        step.get("uses") == "prefix-dev/setup-pixi@v0.10.0"
        and step.get("with", {}).get("cache") is True
        for step in macos["steps"]
    )
    assert any(
        "cmake -S . -B build/macos" in command
        and "-DCMAKE_BUILD_TYPE=Release" in command
        and "-DPYNETFT_BUILD_TESTING=ON" in command
        for command in commands
    )
    assert any("cmake --build build/macos" in command for command in commands)
    assert any(
        "ctest --test-dir build/macos --output-on-failure" in command for command in commands
    )
    assert "pixi run install" in commands
    assert "pixi run python -m pytest -q tests/python tests/integration" in commands


def test_macos_ci_never_targets_a_hardware_sensor() -> None:
    with (ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    serialized_job = yaml.safe_dump(workflow["jobs"]["macos"])

    assert "hardware-test" not in serialized_job
    assert "hardware_test.py" not in serialized_job
    assert "NETFT_SENSOR" not in serialized_job
    assert search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", serialized_job) is None


def test_python_matrix_collection_does_not_require_quality_dependencies() -> None:
    blocker = """
import importlib.abc
import pytest
import sys

class BlockQualityDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in {"mypy", "yaml"}:
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockQualityDependencies())
raise SystemExit(pytest.main([
    "--collect-only",
    "-q",
    "tests/python",
    "tests/integration",
]))
"""
    completed = run(
        [executable, "-c", blocker],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_codeql_cpp_analysis_uses_official_inline_suppression_query() -> None:
    with (ROOT / ".github/workflows/codeql.yml").open(encoding="utf-8") as stream:
        workflow = yaml.safe_load(stream)
    analyze = workflow["jobs"]["analyze"]
    matrix = analyze["strategy"]["matrix"]["include"]
    configurations = {
        entry["language"]: (entry["build-mode"], entry["suppression-pack"]) for entry in matrix
    }
    init_steps = [
        step
        for step in analyze["steps"]
        if str(step.get("uses", "")).startswith("github/codeql-action/init@")
    ]

    assert configurations == {
        "python": ("none", ""),
        "c-cpp": ("manual", "+codeql/cpp-queries:AlertSuppression.ql"),
    }
    assert len(init_steps) == 2
    python_init = next(step for step in init_steps if step["if"] == "matrix.language == 'python'")
    cpp_init = next(step for step in init_steps if step["if"] == "matrix.language == 'c-cpp'")
    assert "packs" not in python_init["with"]
    assert cpp_init["with"]["packs"] == "${{ matrix.suppression-pack }}"
    assert all("queries" not in step["with"] for step in init_steps)
