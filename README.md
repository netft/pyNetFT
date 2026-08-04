# pyNetFT

[![CI](https://github.com/netft/pyNetFT/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/netft/pyNetFT/actions/workflows/ci.yml)
[![Wheels](https://github.com/netft/pyNetFT/actions/workflows/wheels.yml/badge.svg?branch=main)](https://github.com/netft/pyNetFT/actions/workflows/wheels.yml)
[![PyPI](https://img.shields.io/pypi/v/pynetft)](https://pypi.org/project/pynetft/)
[![CodeQL](https://github.com/netft/pyNetFT/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/netft/pyNetFT/actions/workflows/codeql.yml)
[![Coverage](https://codecov.io/gh/netft/pyNetFT/graph/badge.svg?branch=main)](https://codecov.io/gh/netft/pyNetFT)
[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.14-blue)](https://pypi.org/project/pynetft/)
[![License](https://img.shields.io/github/license/netft/pyNetFT?label=license)](LICENSE)

pyNetFT is a synchronous, typed Python SDK for ATI Net F/T Ethernet
force/torque sensors. It discovers the active sensor calibration and streams
RDT measurements through a reviewed snapshot of the native
[netft-cpp](https://github.com/netft/netft-cpp) core.

## Features

- Exposes raw counts, calibrated measurements, native units, and stream health.
- Provides blocking iterator and callback delivery without requiring NumPy.
- Ships typed, self-contained wheels with the native core and HTTP-only curl.
- Supports explicit reconnect and fail-stop recovery behavior.

## Installation

| Install method | Platform | Support |
| --- | --- | --- |
| PyPI wheel | Linux and macOS (x86-64 and ARM64), Windows (x86-64), CPython 3.10–3.14 | Supported |
| Source | Linux, macOS, Windows, CPython 3.10–3.14 | Best effort |

Install from PyPI:

```bash
python -m pip install pynetft
```

Supported wheels include curl and require no separate curl installation. A
source build requires a C++17 compiler, CMake 3.16 or newer, and system
libcurl 7.63.0 or newer.

## Quick start

```python
from pynetft import Client, Config

config = Config(sensor_host="192.168.1.1")

with Client(config) as client:
    sample = next(client.samples(timeout=1.0))
    print(sample.force, sample.force_unit.value)
    print(sample.torque, sample.torque_unit.value)
```

`192.168.1.1` is the ATI factory-default sensor address. Replace it with the
address configured for your sensor. Samples preserve the units reported by the
sensor, including the common ATI combination of newtons and
newton-millimeters.

## Documentation

- [Python SDK tutorial](https://netft.dev/docs/tutorials/sdks/python)
- [Python API reference](https://netft.dev/docs/references/python-api/overview)
- [Units, status, and faults](https://netft.dev/docs/references/data-formats/units-status-and-faults)
- [Security and safety](https://netft.dev/docs/references/security-and-safety)
- [Migrating from pyNetFT 1.x](docs/migration-2.md)

The deprecated `NetFT` and `Response` interfaces remain available throughout
2.x. New applications should use `Client`, `Config`, and `Sample`. PyPy and
asyncio are not supported by the 2.x package.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment, tests,
hardware-testing policy, and native-core synchronization rules. Report
security issues through [SECURITY.md](SECURITY.md).

## License

pyNetFT is licensed under the [Apache License 2.0](LICENSE). Previous pyNetFT,
netft-cpp, and curl license notices remain in the source and distribution
artifacts.
