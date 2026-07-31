# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Fixed

- Update the pinned native core to netft-cpp 0.3.1 so fail-stop clients do not receive
  stalled or backward FT-sequence samples before the corresponding fault.

## 2.1.0 - 2026-07-29

### Added

- Publish self-contained CPython 3.10–3.14 wheels for 64-bit Windows.

### Changed

- Update the pinned native core to netft-cpp 0.3.0, including its WinSock transport and cross-platform lifecycle coverage.
- Build a pinned static HTTP-only curl dependency for Windows wheels.

## 2.0.1 - 2026-07-25

### Added

- Publish self-contained CPython 3.10–3.14 wheels for macOS 11 or newer on Intel and Apple Silicon.

### Changed

- Share the pinned static HTTP-only curl 8.21.0 build across Linux and macOS wheel production without requiring a user-installed curl.

## 2.0.0 - 2026-07-24

### Added

- Add a typed synchronous client backed by the [netft-cpp 0.2.2](https://github.com/netft/netft-cpp/releases/tag/v0.2.2) core, including raw counts, sensor-unit measurements, health, recovery, iterator delivery, and safe callback delivery.
- Publish self-contained CPython 3.10-3.14 Linux wheels for x86_64 and AArch64.

### Changed

- Replace the standalone Python UDP implementation with a pinned native core, including the upstream manylinux2014 compatibility fix, and adopt Apache-2.0 licensing.
- Require libcurl 7.63.0 or newer for source builds, matching the first release that provides the URL API used by sensor discovery.
- Keep the 1.x API as a deprecated adapter for the complete 2.x series.

## 1.0.3

- Last release of the standalone pure-Python implementation.
