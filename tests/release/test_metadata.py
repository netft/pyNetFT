from __future__ import annotations

import base64
import importlib.util
import re
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_tool(name: str) -> ModuleType:
    path = ROOT / "tools" / f"{name}.py"
    assert path.is_file()
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _workflow() -> dict[str, object]:
    with (ROOT / ".github" / "workflows" / "release.yml").open(encoding="utf-8") as stream:
        return yaml.load(stream, Loader=yaml.BaseLoader)


def _write_complete_inventory(root: Path) -> list[str]:
    wheel_names = []
    for python in ("cp310", "cp311", "cp312", "cp313", "cp314"):
        wheel_names.extend(
            (
                f"pynetft-2.0.1-{python}-{python}-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                f"pynetft-2.0.1-{python}-{python}-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
                f"pynetft-2.0.1-{python}-{python}-macosx_11_0_x86_64.whl",
                f"pynetft-2.0.1-{python}-{python}-macosx_11_0_arm64.whl",
            )
        )
    for name in wheel_names:
        (root / name).touch()
    (root / "pynetft-2.0.1.tar.gz").touch()
    return wheel_names


def _write_complete_auditwheel_inventory(root: Path) -> None:
    for python in ("cp310", "cp311", "cp312", "cp313", "cp314"):
        for platform in (
            "manylinux2014_x86_64.manylinux_2_17_x86_64",
            "manylinux2014_aarch64.manylinux_2_17_aarch64",
            "macosx_11_0_x86_64",
            "macosx_11_0_arm64",
        ):
            (root / f"pynetft-2.0.1-{python}-{python}-{platform}.whl").touch()
    (root / "pynetft-2.0.1.tar.gz").touch()


def _git(repository: Path, *arguments: str, input_text: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        input=input_text,
        text=True,
    ).stdout.strip()


def _initialize_repository(repository: Path) -> None:
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "Release Test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    _git(repository, "commit", "--allow-empty", "-q", "-m", "initial")
    _git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")


def _generate_signing_key(path: Path) -> Path:
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
    )
    return path


def _write_allowed_signers(path: Path, principal: str, public_key: Path) -> None:
    key_type, key_data, *_ = public_key.read_text(encoding="utf-8").split()
    path.write_text(
        f'{principal} namespaces="git" {key_type} {key_data}\n',
        encoding="utf-8",
    )


def _sign_tag(repository: Path, tag: str, key: Path) -> None:
    _git(
        repository,
        "-c",
        "gpg.format=ssh",
        "-c",
        f"user.signingkey={key}",
        "tag",
        "-s",
        tag,
        "-m",
        tag,
    )


def test_release_versions_and_changelog_heading_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert version == "2.0.1"
    assert re.search(
        rf"^project\(pynetft VERSION {re.escape(version)} LANGUAGES CXX\)$",
        cmake,
        re.MULTILINE,
    )
    assert re.search(
        rf"^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}$",
        changelog,
        re.MULTILINE,
    )


def test_core_snapshot_identifies_the_pinned_release() -> None:
    metadata = dict(
        line.split("=", 1)
        for line in (ROOT / "core" / "UPSTREAM").read_text(encoding="utf-8").splitlines()
    )

    assert metadata["repository"] == "https://github.com/netft/netft-cpp"
    assert metadata["tag"] == "v0.2.2"
    assert metadata["commit"] == "e424c401587052f03de9b94f76f1e86b78902105"

    core_cmake = (ROOT / "core" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert re.search(
        r"^project\(netft VERSION 0\.2\.2 LANGUAGES CXX\)$",
        core_cmake,
        re.MULTILINE,
    )


def test_core_snapshot_contains_only_the_controlled_upstream_paths() -> None:
    metadata = dict(
        line.split("=", 1)
        for line in (ROOT / "core" / "UPSTREAM").read_text(encoding="utf-8").splitlines()
    )
    selected = set(metadata["paths"].split(","))
    inventory = {
        path.relative_to(ROOT / "core").as_posix()
        for path in (ROOT / "core").rglob("*")
        if path.is_file()
    }
    payload = inventory - {"UPSTREAM", "SNAPSHOT.sha256"}

    assert selected == {"CMakeLists.txt", "LICENSE", "app", "cmake", "include", "src"}
    assert payload
    assert all(path.split("/", 1)[0] in selected for path in payload)
    assert all(
        part not in {".git", ".github", "build", "test", "tests"}
        for path in inventory
        for part in path.split("/")
    )


def test_source_build_metadata_requires_libcurl_7_63() -> None:
    pixi = tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))
    core_cmake = (ROOT / "core" / "CMakeLists.txt").read_text(encoding="utf-8")
    installed_config = (ROOT / "core" / "cmake" / "netftConfig.cmake.in").read_text(
        encoding="utf-8"
    )

    assert pixi["dependencies"]["libcurl"] == ">=7.63.0"
    assert re.search(
        r"^find_package\(CURL 7\.63\.0 REQUIRED\)$",
        core_cmake,
        re.MULTILINE,
    )
    assert re.search(
        r"^find_dependency\(CURL 7\.63\.0\)$",
        installed_config,
        re.MULTILINE,
    )


def test_release_metadata_tool_validates_tag_and_extracts_current_section() -> None:
    tool = _load_tool("release_metadata")

    metadata = tool.validate_release(ROOT, "v2.0.1")
    notes = tool.changelog_notes(ROOT / "CHANGELOG.md", metadata.version)

    assert metadata.version == "2.0.1"
    assert metadata.tag == "v2.0.1"
    assert metadata.release_date.isoformat() == "2026-07-25"
    assert notes

    with pytest.raises(tool.ReleaseMetadataError):
        tool.validate_release(ROOT, "v2.0.0")


def test_release_workflow_has_read_only_defaults_and_tag_only_trigger() -> None:
    workflow = _workflow()

    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request" not in workflow["on"]
    validation_commands = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["validate"]["steps"] if step.get("run")
    )
    assert "verify-tag --raw" in validation_commands
    assert "gpg.ssh.allowedSignersFile" in validation_commands
    assert "merge-base --is-ancestor" in validation_commands
    assert "refs/remotes/origin/main" in validation_commands
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            action = step.get("uses")
            if action is not None:
                assert re.search(r"@[0-9a-f]{40}$", action)


def test_release_workflow_pins_every_action_with_a_version_comment() -> None:
    content = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    action_lines = [line.strip() for line in content.splitlines() if "uses:" in line]

    assert action_lines
    assert all(re.search(r"@[0-9a-f]{40}\s+#\s+\S+$", line) for line in action_lines)


def test_release_setup_pixi_steps_do_not_use_shared_caches() -> None:
    workflow = _workflow()
    setup_steps: list[tuple[str, dict[str, object]]] = []

    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            action = step.get("uses", "")
            if action.startswith("prefix-dev/setup-pixi@"):
                setup_steps.append((job_name, step))

    assert setup_steps
    for job_name, step in setup_steps:
        assert step.get("with", {}).get("cache") == "false", job_name


def test_release_allowed_signers_contains_only_public_git_key_material() -> None:
    path = ROOT / ".github" / "release-allowed-signers"
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert len(lines) == 1
    principal, namespace, key_type, key_data = lines[0].split()
    assert principal == "netft-release"
    assert namespace == 'namespaces="git"'
    assert key_type == "ssh-ed25519"
    assert len(base64.b64decode(key_data, validate=True)) > 32


def test_release_workflow_builds_and_validates_the_complete_artifact_matrix() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    wheels = jobs["wheels"]
    matrix = wheels["strategy"]["matrix"]["include"]

    assert {entry["arch"] for entry in matrix} == {"x86_64", "aarch64"}
    assert len({entry["artifact"] for entry in matrix}) == 2
    assert all(entry["runner"] for entry in matrix)
    assert jobs["sdist"]["needs"] == "validate"
    assert wheels["needs"] == "validate"

    assemble = jobs["assemble"]
    assert set(assemble["needs"]) == {"wheels", "macos-wheels", "sdist"}
    download_steps = [
        step
        for step in assemble["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]
    assert any(
        step.get("with", {}).get("pattern") == "release-wheels-*"
        and step.get("with", {}).get("merge-multiple") == "true"
        for step in download_steps
    )
    assemble_run = "\n".join(step.get("run", "") for step in assemble["steps"] if step.get("run"))
    assert "tools/check_release_artifacts.py" in assemble_run
    assert "python tools/check_wheel.py artifacts/*.whl" in assemble_run
    assert (
        'python tools/check_wheel.py --self-contained --auditwheel "${linux_wheels[@]}"'
        in assemble_run
    )
    assert "--auditwheel artifacts/*.whl" not in assemble_run
    assert "--delocate" not in assemble_run
    assert "otool" not in assemble_run
    assert "tools/check_sdist.py" in assemble_run
    assert "twine check" in assemble_run
    assert "matching_wheel=(artifacts/*-cp314-cp314-*manylinux*x86_64.whl)" in assemble_run
    assert "sha256sum *" in assemble_run


def test_release_workflow_builds_and_native_validates_macos_wheels() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cibuildwheel = project["tool"]["cibuildwheel"]
    workflow = _workflow()
    macos = workflow["jobs"]["macos-wheels"]

    assert macos["needs"] == "validate"
    assert macos["runs-on"] == "${{ matrix.runner }}"
    assert macos["strategy"]["matrix"]["include"] == [
        {
            "arch": "x86_64",
            "runner": "macos-15-intel",
            "artifact": "release-wheels-macos-x86_64",
        },
        {
            "arch": "arm64",
            "runner": "macos-15",
            "artifact": "release-wheels-macos-arm64",
        },
    ]
    assert cibuildwheel["build"] == [
        "cp310-*",
        "cp311-*",
        "cp312-*",
        "cp313-*",
        "cp314-*",
    ]
    assert cibuildwheel["test-command"] == (
        "python -m pip check && python -m pytest {project}/tests/artifact -q"
    )
    assert cibuildwheel["test-requires"] == ["pytest"]

    install_run = next(
        step["run"] for step in macos["steps"] if "pip install" in step.get("run", "")
    )
    assert "cibuildwheel==3.4.1" in install_run
    assert "delocate" in install_run
    assert "twine" in install_run

    build_step = next(
        step for step in macos["steps"] if "python -m cibuildwheel" in step.get("run", "")
    )
    assert "--platform macos" in build_step["run"]
    assert build_step["env"]["CIBW_ARCHS_MACOS"] == "${{ matrix.arch }}"

    validation_index = next(
        index
        for index, step in enumerate(macos["steps"])
        if "tools/check_wheel.py" in step.get("run", "")
    )
    upload_index = next(
        index
        for index, step in enumerate(macos["steps"])
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    validation_run = macos["steps"][validation_index]["run"]
    assert "python -m twine check wheelhouse/*.whl" in validation_run
    assert (
        "python tools/check_wheel.py --self-contained --delocate wheelhouse/*.whl" in validation_run
    )
    assert validation_index < upload_index
    assert macos["steps"][upload_index]["with"]["name"] == "${{ matrix.artifact }}"
    assert macos["steps"][upload_index]["with"]["path"] == "wheelhouse/*.whl"
    assert macos["steps"][upload_index]["with"]["if-no-files-found"] == "error"


def test_release_workflow_uses_oidc_only_for_pypi_and_separates_github_write() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    publish = jobs["publish-pypi"]
    draft_release = jobs["draft-release"]
    finalize_release = jobs["finalize-release"]

    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert draft_release["permissions"] == {"contents": "write"}
    assert finalize_release["permissions"] == {"contents": "write"}
    assert draft_release["needs"] == ["assemble", "attest"]
    assert publish["needs"] == ["assemble", "draft-release"]
    assert finalize_release["needs"] == ["draft-release", "publish-pypi"]
    assert all("password" not in step.get("with", {}) for step in publish["steps"])
    assert all("token" not in step.get("with", {}) for step in publish["steps"])
    draft_commands = "\n".join(
        step.get("run", "") for step in draft_release["steps"] if step.get("run")
    )
    assert "gh release create" in draft_commands
    assert "--draft" in draft_commands
    assert "gh release upload" in draft_commands
    assert "--clobber" in draft_commands
    assert "isDraft" in draft_commands
    assert len(finalize_release["steps"]) == 1
    finalize_command = finalize_release["steps"][0]["run"]
    assert "gh release edit" in finalize_command
    assert "--draft=false" in finalize_command
    assert "gh release create" not in finalize_command
    assert "gh release upload" not in finalize_command


def test_release_aggregate_provisions_clean_sdist_build_dependencies() -> None:
    workflow = _workflow()
    commands = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["assemble"]["steps"] if step.get("run")
    )

    assert "build-essential" in commands
    assert "libcurl4-openssl-dev" in commands
    assert "env CC=gcc CXX=g++" in commands


def test_release_artifact_inventory_rejects_missing_or_duplicate_matrix_entries(
    tmp_path: Path,
) -> None:
    tool = _load_tool("check_release_artifacts")
    wheel_names = _write_complete_inventory(tmp_path)

    tool.validate_inventory(tmp_path, "2.0.1")

    missing_macos_wheel = next(name for name in wheel_names if "macosx_11_0_arm64" in name)
    (tmp_path / missing_macos_wheel).unlink()
    with pytest.raises(tool.ReleaseArtifactError):
        tool.validate_inventory(tmp_path, "2.0.1")

    (tmp_path / missing_macos_wheel).touch()
    duplicate = tmp_path / "duplicate" / wheel_names[0]
    duplicate.parent.mkdir()
    duplicate.touch()
    with pytest.raises(tool.ReleaseArtifactError):
        tool.validate_inventory(tmp_path, "2.0.1")


def test_release_artifact_inventory_accepts_auditwheel_platform_tag_order(
    tmp_path: Path,
) -> None:
    tool = _load_tool("check_release_artifacts")
    _write_complete_auditwheel_inventory(tmp_path)

    tool.validate_inventory(tmp_path, "2.0.1")


@pytest.mark.parametrize(
    ("original_platform", "replacement"),
    (
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp310-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp310-linux_x86_64.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp310-manylinux2014_x86_64.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.linux_x86_64.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.1-cp310-cp310-manylinux_2_17_x86_64."
            "manylinux2014_x86_64.manylinux2014_x86_64.whl",
        ),
        (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "pynetft-2.0.2-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        ),
        (
            "macosx_11_0_x86_64",
            "pynetft-2.0.1-cp310-cp310-macosx_11_0_universal2.whl",
        ),
        (
            "macosx_11_0_x86_64",
            "pynetft-2.0.1-cp310-cp310-macosx_11_1_x86_64.whl",
        ),
    ),
)
def test_release_artifact_inventory_rejects_invalid_python_or_platform_tags(
    tmp_path: Path, original_platform: str, replacement: str
) -> None:
    tool = _load_tool("check_release_artifacts")
    wheel_names = _write_complete_inventory(tmp_path)
    original = next(name for name in wheel_names if name.endswith(f"{original_platform}.whl"))
    (tmp_path / original).unlink()
    (tmp_path / replacement).touch()

    with pytest.raises(tool.ReleaseArtifactError):
        tool.validate_inventory(tmp_path, "2.0.1")


def test_release_tag_verifier_accepts_authorized_main_tag(tmp_path: Path) -> None:
    tool = _load_tool("verify_release_tag")
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    key = _generate_signing_key(tmp_path / "authorized")
    allowed_signers = tmp_path / "allowed_signers"
    _write_allowed_signers(allowed_signers, "netft-release", key.with_suffix(".pub"))
    _sign_tag(repository, "v2.0.0", key)

    tool.verify_release_tag(
        repository,
        "v2.0.0",
        allowed_signers,
        principal="netft-release",
        main_ref="refs/remotes/origin/main",
    )


def test_release_tag_verifier_rejects_authorized_non_main_tag(tmp_path: Path) -> None:
    tool = _load_tool("verify_release_tag")
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    key = _generate_signing_key(tmp_path / "authorized")
    allowed_signers = tmp_path / "allowed_signers"
    _write_allowed_signers(allowed_signers, "netft-release", key.with_suffix(".pub"))
    _git(repository, "switch", "-q", "-c", "feature")
    _git(repository, "commit", "--allow-empty", "-q", "-m", "feature")
    _sign_tag(repository, "v2.0.0", key)

    with pytest.raises(tool.ReleaseTagError):
        tool.verify_release_tag(
            repository,
            "v2.0.0",
            allowed_signers,
            principal="netft-release",
            main_ref="refs/remotes/origin/main",
        )


def test_release_tag_verifier_rejects_unsigned_and_unknown_signers(tmp_path: Path) -> None:
    tool = _load_tool("verify_release_tag")
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    authorized = _generate_signing_key(tmp_path / "authorized")
    unknown = _generate_signing_key(tmp_path / "unknown")
    allowed_signers = tmp_path / "allowed_signers"
    _write_allowed_signers(allowed_signers, "netft-release", authorized.with_suffix(".pub"))
    _git(repository, "tag", "-a", "v2.0.0", "-m", "v2.0.0")

    with pytest.raises(tool.ReleaseTagError):
        tool.verify_release_tag(
            repository,
            "v2.0.0",
            allowed_signers,
            principal="netft-release",
            main_ref="refs/remotes/origin/main",
        )

    _git(repository, "tag", "-d", "v2.0.0")
    _sign_tag(repository, "v2.0.0", unknown)
    with pytest.raises(tool.ReleaseTagError):
        tool.verify_release_tag(
            repository,
            "v2.0.0",
            allowed_signers,
            principal="netft-release",
            main_ref="refs/remotes/origin/main",
        )


def test_release_tag_verifier_rejects_fake_and_tampered_signatures(tmp_path: Path) -> None:
    tool = _load_tool("verify_release_tag")
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    key = _generate_signing_key(tmp_path / "authorized")
    allowed_signers = tmp_path / "allowed_signers"
    _write_allowed_signers(allowed_signers, "netft-release", key.with_suffix(".pub"))
    commit = _git(repository, "rev-parse", "HEAD")
    fake_tag = (
        f"object {commit}\n"
        "type commit\n"
        "tag v2.0.0\n"
        "tagger Release Test <release-test@example.invalid> 0 +0000\n\n"
        "v2.0.0\n"
        "-----BEGIN SSH SIGNATURE-----\n"
        "invalid\n"
        "-----END SSH SIGNATURE-----\n"
    )
    fake_object = _git(repository, "hash-object", "-t", "tag", "-w", "--stdin", input_text=fake_tag)
    _git(repository, "update-ref", "refs/tags/v2.0.0", fake_object)

    with pytest.raises(tool.ReleaseTagError):
        tool.verify_release_tag(
            repository,
            "v2.0.0",
            allowed_signers,
            principal="netft-release",
            main_ref="refs/remotes/origin/main",
        )

    _git(repository, "tag", "-d", "v2.0.0")
    _sign_tag(repository, "v2.0.0", key)
    signed_content = _git(repository, "cat-file", "tag", "v2.0.0")
    tampered_object = _git(
        repository,
        "hash-object",
        "-t",
        "tag",
        "-w",
        "--stdin",
        input_text=signed_content.replace("\nv2.0.0\n", "\ntampered\n", 1) + "\n",
    )
    _git(repository, "update-ref", "refs/tags/v2.0.0", tampered_object)

    with pytest.raises(tool.ReleaseTagError):
        tool.verify_release_tag(
            repository,
            "v2.0.0",
            allowed_signers,
            principal="netft-release",
            main_ref="refs/remotes/origin/main",
        )
