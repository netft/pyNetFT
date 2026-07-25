# pyNetFT

[![CI](https://github.com/netft/pyNetFT/actions/workflows/ci.yml/badge.svg)](https://github.com/netft/pyNetFT/actions/workflows/ci.yml)
[![Wheels](https://github.com/netft/pyNetFT/actions/workflows/wheels.yml/badge.svg)](https://github.com/netft/pyNetFT/actions/workflows/wheels.yml)
[![CodeQL](https://github.com/netft/pyNetFT/actions/workflows/codeql.yml/badge.svg)](https://github.com/netft/pyNetFT/actions/workflows/codeql.yml)
[![Codecov](https://codecov.io/gh/netft/pyNetFT/branch/main/graph/badge.svg)](https://codecov.io/gh/netft/pyNetFT)
[![PyPI](https://img.shields.io/pypi/v/pynetft.svg)](https://pypi.org/project/pynetft/)
[![Python](https://img.shields.io/pypi/pyversions/pynetft.svg)](https://pypi.org/project/pynetft/)
[![License](https://img.shields.io/github/license/netft/pyNetFT.svg)](https://github.com/netft/pyNetFT/blob/main/LICENSE)

pyNetFT is a synchronous, typed Python client for ATI Industrial Automation Net F/T Ethernet force/torque sensors. It discovers the sensor calibration, streams RDT measurements through a native C++ core, and exposes raw counts, physical measurements, health, and recovery information without requiring NumPy.

- **Tested native core:** the protocol and recovery implementation is pinned to [netft-cpp 0.2.2](https://github.com/netft/netft-cpp/releases/tag/v0.2.2), includes its GCC 10/manylinux2014 compatibility fix and corrected libcurl minimum, and is exercised with offline fake sensors and native sanitizers.
- **Sensor-aware data:** calibration, force and torque units, configuration revisions, sequence progress, and faults remain visible to the application.
- **Self-contained typed wheels:** Linux wheels include the native core and a minimal static HTTP-only curl build, plus inline type information for Python 3.10–3.14.

## Supported platforms

| Installation | Python | Platform | Architecture | Support |
| --- | --- | --- | --- | --- |
| PyPI wheel | CPython 3.10–3.14 | manylinux2014 or newer Linux | x86_64 | Supported |
| PyPI wheel | CPython 3.10–3.14 | manylinux2014 or newer Linux | AArch64 | Supported |
| Source build | CPython 3.10–3.14 | POSIX | Host compiler architecture | Best effort |

Windows, macOS wheels, PyPy, and asyncio are not supported by the 2.x package.

## Installation

Install a supported wheel from PyPI:

```bash
python -m pip install pynetft
```

For a source build, use a C++17 compiler, CMake 3.16 or newer, and libcurl 7.63.0 or newer:

```bash
git clone https://github.com/netft/pyNetFT.git
cd pyNetFT
python -m pip install .
```

Source builds use the checked-in native core and do not download `netft-cpp`.

## Quick start

The address below is the ATI factory default. Replace it with the address assigned to your sensor.

```python
from pynetft import Client, Config

config = Config(sensor_host="192.168.1.1")

with Client(config) as client:
    sample = next(client.samples(timeout=1.0))
    print(sample.force, sample.force_unit.value)
    print(sample.torque, sample.torque_unit.value)
```

`Client.samples()` provides blocking iterator delivery. A read timeout raises `TimeoutError`, while a terminal sensor or transport fault raises `SensorFaultError` with structured fault and health data. Applications that integrate with a callback-driven loop can instead pass `callback=` to `Client`; the two delivery modes are mutually exclusive for a client run. See the [API reference](https://github.com/netft/pyNetFT/blob/main/docs/api.md) for lifecycle, callback, timeout, health, and error behavior.

### Units and raw counts

`Sample.force` and `Sample.torque` preserve the units reported by the sensor, including the common ATI combination of newtons and newton-millimeters. pyNetFT does not apply ROS-specific SI conversion. `Sample.wrench` is the six-element physical-value tuple `(Fx, Fy, Fz, Tx, Ty, Tz)`, while `Sample.raw_wrench` contains the six signed integer counts from the RDT record.

Automatic discovery is the default and should be preferred when the sensor configuration is authoritative. A complete `Calibration` override is available when independently verified fixed values are required.

### Migrating from pyNetFT 1.x

The deprecated `NetFT` and `Response` interfaces remain available throughout 2.x. New code should use `Client`, `Config`, and `Sample`; see the [2.0 migration guide](https://github.com/netft/pyNetFT/blob/main/docs/migration-2.md) for exact call and field mappings.

## Network security

ATI configuration discovery uses HTTP and RDT streaming uses unauthenticated UDP. Deploy the sensor and client on a trusted, isolated network segment, and do not expose either device protocol directly to the Internet or an untrusted shared network. See the [security policy](https://github.com/netft/pyNetFT/blob/main/SECURITY.md) for the threat model and vulnerability reporting instructions.

## Hardware safety

Force/torque measurements can affect motion and protective limits. Validate discovered calibration and units before enabling a controller, detect stale or faulted data, and retain an independent safety-rated control path. `Client.bias()` changes the sensor's software bias; call it only when the sensor is unloaded and the operation is explicitly authorized.

## Contributing

Bug reports, hardware compatibility reports, documentation improvements, and focused code contributions are welcome. The [contribution guide](https://github.com/netft/pyNetFT/blob/main/CONTRIBUTING.md) covers the Pixi environment, offline checks, hardware authorization, and native-core synchronization rules.

## License

pyNetFT is licensed under the [Apache License 2.0](https://github.com/netft/pyNetFT/blob/main/LICENSE). The [previous pyNetFT MIT license](https://github.com/netft/pyNetFT/blob/main/LICENSES/MIT.txt), the synchronized [netft-cpp license](https://github.com/netft/pyNetFT/blob/main/core/LICENSE), and the [curl license notice](https://github.com/netft/pyNetFT/blob/main/LICENSES/curl.txt) are retained with the source and distribution artifacts.
