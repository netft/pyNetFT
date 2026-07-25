#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


class ReleaseTagError(RuntimeError):
    pass


def _run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
    )


def _validate_allowed_principal(path: Path, principal: str) -> None:
    principals = {
        line.split(maxsplit=1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if principals != {principal}:
        raise ReleaseTagError("allowed_principal")


def verify_release_tag(
    repository: Path,
    tag: str,
    allowed_signers: Path,
    *,
    principal: str,
    main_ref: str,
) -> None:
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None:
        raise ReleaseTagError("tag")
    allowed_signers = allowed_signers.resolve()
    _validate_allowed_principal(allowed_signers, principal)
    verification = _run_git(
        repository,
        "-c",
        "gpg.format=ssh",
        "-c",
        f"gpg.ssh.allowedSignersFile={allowed_signers}",
        "verify-tag",
        "--raw",
        tag,
    )
    output = f"{verification.stdout}\n{verification.stderr}"
    expected = f'Good "git" signature for {principal} with '
    if verification.returncode != 0 or expected not in output:
        raise ReleaseTagError("signature")

    main = _run_git(repository, "rev-parse", "--verify", main_ref)
    if main.returncode != 0:
        raise ReleaseTagError("main_ref")
    ancestor = _run_git(
        repository,
        "merge-base",
        "--is-ancestor",
        f"{tag}^{{commit}}",
        main_ref,
    )
    if ancestor.returncode != 0:
        raise ReleaseTagError("main_ancestry")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--allowed-signers",
        type=Path,
        default=Path(".github/release-allowed-signers"),
    )
    parser.add_argument("--principal", default="netft-release")
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    arguments = parser.parse_args()
    verify_release_tag(
        Path.cwd(),
        arguments.tag,
        arguments.allowed_signers,
        principal=arguments.principal,
        main_ref=arguments.main_ref,
    )


if __name__ == "__main__":
    main()
