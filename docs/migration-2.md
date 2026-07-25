# Migrating from pyNetFT 1.x to 2.x

pyNetFT 2.0 replaces the standalone Python UDP implementation with the native `netft-cpp` core and introduces a typed, synchronous API. The import and distribution name remains `pynetft`.

`NetFT` and `Response` remain as deprecated adapters for the complete 2.x series. They are scheduled for removal in 3.0.

## Exact API mapping

```text
NetFT.connect()             -> Client.start() or context entry
NetFT.disconnect()          -> Client.stop() or context exit
NetFT.get_data()            -> next(Client.samples()).raw_wrench
NetFT.get_converted_data()  -> next(Client.samples()).wrench
NetFT.bias()                -> Client.bias()
Response.FTData             -> Sample.raw_wrench or Sample.wrench
```

Sequence and status fields map directly:

| 1.x | 2.x |
| --- | --- |
| `Response.rdt_sequence` | `Sample.rdt_sequence` |
| `Response.ft_sequence` | `Sample.ft_sequence` |
| `Response.status` | `Sample.status` |

## Before and after

The deprecated 1.x shape remains functional:

```python
from pynetft import NetFT

sensor = NetFT("192.168.1.1")
sensor.connect()
try:
    response = sensor.get_converted_data()
    print(response.FTData)
finally:
    sensor.disconnect()
```

New code should use the resource-managed client:

```python
from pynetft import Client, Config

with Client(Config(sensor_host="192.168.1.1")) as client:
    sample = next(client.samples(timeout=1.0))
    print(sample.wrench)
```

## Calibration and units

Omit legacy count parameters to discover counts and units from the sensor. If legacy code provides both `count_per_force` and `count_per_torque`, the adapter interprets them as newtons and newton-millimeters. Supplying only one is an error.

The modern API represents an override explicitly:

```python
from pynetft import Calibration, Config, ForceUnit, TorqueUnit

config = Config(
    sensor_host="192.168.1.1",
    calibration_override=Calibration(
        counts_per_force_unit=1_000_000,
        counts_per_torque_unit=1_000,
        force_unit=ForceUnit.NEWTON,
        torque_unit=TorqueUnit.NEWTON_MILLIMETER,
    ),
)
```

Use only independently verified values. Without an override, `Health.sensor_configuration` reports the discovered product, calibration, source, and revision.

Physical values preserve the sensor-reported units. pyNetFT does not convert torque to newton-meters or otherwise apply ROS conventions.

## Delivery and failures

The 1.x `num_samples` argument is accepted for source compatibility, but values other than `1` produce `DeprecationWarning`. In 2.x, the native core maintains a continuous RDT stream and the bounded Python delivery queue favors the latest sample.

Iterator timeouts raise the built-in `TimeoutError`. Terminal device or transport faults raise `SensorFaultError`, which carries a structured `fault_code` and final `health` snapshot. Applications should replace message parsing with these structured fields.

For callback-based applications, pass `callback=` to `Client` and use `wait()` or `raise_if_failed()` to surface `CallbackError`. Iterator and callback delivery cannot be mixed within one run.
