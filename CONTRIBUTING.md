# Contributing to pyNetFT

Bug reports, hardware compatibility reports, documentation corrections, tests, and focused code changes are welcome.

## Development environment

Install [Pixi](https://pixi.sh), clone the repository, and create the locked environment:

```bash
git clone https://github.com/netft/pyNetFT.git
cd pyNetFT
pixi install
pixi run install
```

The normal test suite is offline with respect to physical hardware and uses local fake HTTP and UDP sensors:

```bash
pixi run test
pixi run check
pixi run coverage
```

`pixi run check` verifies the controlled core snapshot, tests, Python and C++ formatting, Ruff, mypy, and native clang-tidy analysis. Run the complete relevant command set before opening a pull request.

## Test-driven changes

Use a red-green-refactor workflow for executable changes:

1. Add or adjust the smallest behavioral test that demonstrates the missing behavior or defect.
2. Run it and confirm that it fails for the expected reason.
3. Implement the smallest complete change that makes it pass.
4. Run the focused test and then the full relevant suite.
5. Refactor only while the tests remain green.

Tests should verify public behavior, protocol rules, package metadata, serialized fields, artifact contents, or necessary private invariants. Do not pin README, changelog, release-note, help, diagnostic, log, or complete error-message prose. Executable documentation examples may be compiled or run to verify that they use the public API correctly.

No default test may depend on a physical sensor or external network service.

## Formatting and type checks

Format supported source files with:

```bash
pixi run format
```

Before submitting, run:

```bash
pixi run format-check
pixi run lint
pixi run type-check
pixi run native-tidy
```

Keep Python 3.10 compatibility, retain complete public type annotations, and keep the native layer C++17-compatible. Avoid unrelated formatting or refactoring in focused changes.

## Native core snapshot

`core/` is a controlled source snapshot of the exact `netft-cpp` release recorded in `core/UPSTREAM`. Do not edit snapshot files directly.

Protocol, transport, discovery, recovery, or health fixes belong in [netft-cpp](https://github.com/netft/netft-cpp) first. After a signed upstream release:

1. check out the exact clean release commit in a local `netft-cpp` repository;
2. run `python tools/sync_core.py sync --source /path/to/netft-cpp --tag vX.Y.Z`;
3. run `pixi run snapshot-check`;
4. review `core/UPSTREAM`, the complete snapshot diff, and license material;
5. update Python bindings, documentation, and the package version as required; and
6. run native, Python, fake-sensor, sdist, and wheel validation.

Never fetch or discover `netft-cpp` during a normal package build. Do not mix local snapshot edits with Python-layer changes.

## Hardware testing is opt-in

The default suite must remain safe and hardware-independent. Physical-sensor testing requires explicit authorization from the person responsible for the device and test area. Before a hardware run:

- identify the exact sensor host and expected calibration outside repository files and logs;
- confirm that the address is not a copied documentation example;
- make the mechanical setup safe, stop hazardous motion, and keep people clear;
- state whether the test will stream, disconnect the network, inject faults, or apply bias; and
- record the sensor model, firmware, selected units, and non-sensitive result in the pull request.

Pass the authorized address only through `NETFT_SENSOR_HOST`. Never commit it. The repository hardware check streams without applying bias. Do not call `Client.bias()` unless that separate operation has been explicitly authorized and the sensor is verified unloaded.

## Cross-repository synchronization

The `netft` organization maintains three separate repositories:

- `netft-cpp` is the standalone C++ core and source of truth for shared protocol behavior;
- `pyNetFT` contains a pinned private core snapshot, Python bindings, and the Python public API; and
- `ros-netft` contains its own private core snapshot and ROS integration.

There is no automatic runtime or build-time dependency between these repositories. Synchronize a released core into each consumer through separate, reviewable pull requests. Record the exact upstream tag and commit, port consumer-specific integration independently, run that repository's full supported tests, and document intentional differences. Do not claim the snapshots update in lockstep.

## Release workflow

The project follows Semantic Versioning. Every user-visible change belongs in `CHANGELOG.md`, and breaking changes require migration guidance.

Release preparation updates the package, CMake, changelog, and pinned-core versions together. After the full local check, artifact validation, and authorized non-mutating hardware check pass, merge the release pull request and create a signed `vX.Y.Z` tag from `main`.

Release tags use SSH signing. The public keys authorized for the stable `netft-release` principal are stored in `.github/release-allowed-signers`. Maintainers sign with the corresponding private key outside the repository:

```bash
git -c gpg.format=ssh -c user.signingkey=/path/to/signing-key \
  tag -s vX.Y.Z -m "pyNetFT X.Y.Z"
```

Never commit a private signing key. Verify the tag locally before pushing it:

```bash
git -c gpg.format=ssh \
  -c gpg.ssh.allowedSignersFile=.github/release-allowed-signers \
  verify-tag --raw vX.Y.Z
git merge-base --is-ancestor vX.Y.Z^{commit} origin/main
```

The tag-driven workflow accepts only an authorized signed tag whose commit is an ancestor of `origin/main`. It rebuilds and tests the supported x86_64 and AArch64 wheels and source distribution, validates licenses and native dependencies, attests the artifacts, and creates a draft GitHub Release. Only after that draft exists does the protected `pypi` environment publish through PyPI Trusted Publishing. A final job makes the GitHub Release public after PyPI publication succeeds.

Maintainers must verify the publisher owner, repository, workflow filename, and environment before approving publication. Release credentials do not belong in repository secrets or local configuration.

## Pull requests and licensing

Keep each pull request limited to one coherent change. Describe the problem, chosen behavior, tests run, supported platforms, hardware involvement, and any core or ROS synchronization impact. Update public documentation and `CHANGELOG.md` when users need to know about a change.

All contributions are submitted under the [Apache License 2.0](https://github.com/netft/pyNetFT/blob/main/LICENSE). The prior pyNetFT MIT text and third-party license notices remain in `LICENSES/`.
