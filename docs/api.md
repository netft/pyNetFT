# pyNetFT 2.x API reference

pyNetFT exposes a synchronous public API from the `pynetft` package. The private `pynetft._native` extension is an implementation detail and is not a compatibility surface.

## Client lifecycle

Create a client from an immutable `Config`:

```python
from pynetft import Client, Config

client = Client(Config(sensor_host="192.168.1.1"), queue_size=1)
```

`Client(config, *, queue_size=1, callback=None)` validates the configuration and creates a bounded native delivery queue. The queue drops its oldest pending item when full so memory stays bounded and consumers receive current data. Queue drops are reported by `Health.python_queue_dropped_count`.

The supported lifecycle is:

```text
created/stopped -> connecting -> streaming -> stopped
                         |            |
                         +-> backoff <-+
                         |
                         +-> faulted -> stopped
```

`Client.start(callback=None)` starts a run. Repeating the same-mode start while the Python client still considers that run active is an idempotent no-op, including after the native core has latched a fault but before the delivery path has observed it. Changing between iterator and callback delivery, or replacing a callback during a run, raises `RuntimeError`.

A faulted run must first finish through its delivery path or be explicitly stopped. Iterator delivery observes the closed queue and raises `SensorFaultError`; callback delivery stores the fault, ends the dispatcher, and exposes it through `wait()` or `raise_if_failed()`. Either path stops the Python run. After that, or after an explicit `stop()`, the client can be started again. Calling the same-mode `start()` before one of those steps does not restart the native core.

`Client.stop()` is idempotent and does not raise. It closes the delivery queue, wakes blocked iterator or dispatcher reads, and waits for an externally stopped callback dispatcher to finish. A callback may call `stop()` on its own client, but it must not call `start()` or block in `wait()` on that client.

`Client.__enter__()` starts the client and returns it. `Client.__exit__()` always stops it. To use callback delivery with a context manager, pass the callback to the constructor.

Resource management is explicit: call `stop()` or use a context manager. Object destruction only provides best-effort cleanup.

## Delivery modes

### Iterator delivery

`Client.samples(timeout=None)` returns an iterator over immutable `Sample` values. With `timeout=None`, each read blocks until a sample, stop, or terminal fault. A numeric timeout applies to each iterator read; expiration raises the built-in `TimeoutError`. Normal stop ends the iterator with `StopIteration`. A terminal sensor fault raises `SensorFaultError`.

Only one consumer should read a client's sample iterator. `latest_sample()` and `health()` remain available without consuming the queue.

```python
from pynetft import Client, Config

with Client(Config(sensor_host="192.168.1.1"), queue_size=4) as client:
    for sample in client.samples(timeout=1.0):
        print(sample.wrench)
```

### Callback delivery

Pass `callback: Callable[[Sample], None]` either to the constructor or the first `start()` call:

```python
from threading import Event

from pynetft import Client, Config, Sample

received = Event()

def consume(sample: Sample) -> None:
    print(sample.wrench)
    received.set()


with Client(Config(sensor_host="192.168.1.1"), callback=consume) as client:
    if not received.wait(timeout=1.0):
        client.raise_if_failed()
        raise TimeoutError("the sensor did not produce a sample")
```

Callbacks run serially on a dedicated Python dispatcher thread, never on the native receive worker. Slow callbacks can cause bounded-queue drops. Callback and iterator delivery are mutually exclusive for a run.

If a callback raises, pyNetFT stops the run and stores the original exception. `Client.wait()` and `Client.raise_if_failed()` raise `CallbackError` with that original exception as `__cause__`. `wait(timeout=None)` is valid only in callback mode; a numeric timeout raises the built-in `TimeoutError` without stopping the run. `raise_if_failed()` reports stored callback-delivery failures only. Iterator faults are surfaced by advancing `samples()`, not by `raise_if_failed()`.

## Client methods

| Method | Result and behavior |
| --- | --- |
| `start(callback=None)` | Start iterator or callback delivery. May raise `ConfigurationError`, `DiscoveryError`, `NotConnectedError`, or `RuntimeError` for an invalid delivery-mode transition. |
| `stop()` | Stop idempotently, wake readers, and join an external callback dispatcher. |
| `bias()` | Apply the sensor software-bias command. Requires a running connection and may raise `ConfigurationError` or `NotConnectedError`. |
| `wait_for_first_sample(timeout)` | Return `True` if the current run receives its first sample. Return `False` on timeout, when not running, after a fault, or when stop/restart changes the delivery-queue generation. These `False` cases are not distinguished and this method does not surface the fault. Invalid timeout values raise `ConfigurationError`. |
| `samples(timeout=None)` | Return the blocking iterator described above. |
| `latest_sample()` | Return the newest delivered `Sample`, or `None` before delivery. It does not consume the queue. |
| `health()` | Return an immutable `Health` snapshot. |
| `wait(timeout=None)` | Wait for callback-mode completion, then surface its stored failure. A wait timeout does not stop the run. |
| `raise_if_failed()` | In callback delivery, surface a stored callback or terminal sensor failure without waiting. It does not inspect or surface iterator-delivery faults. |

## Configuration and calibration

`Config` is an immutable dataclass with these fields:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `sensor_host` | `str` | `"192.168.1.1"` | Sensor host used for HTTP discovery and RDT. |
| `rdt_port` | `int` | `49152` | UDP RDT port. |
| `http_port` | `int` | `80` | HTTP configuration port. |
| `receive_timeout` | `float` | `0.1` | UDP receive timeout in seconds. |
| `configuration_connect_timeout` | `float` | `0.5` | HTTP connection timeout in seconds. |
| `configuration_timeout` | `float` | `1.0` | Total configuration response timeout in seconds. |
| `reconnect_initial_delay` | `float` | `0.25` | Initial reconnect backoff in seconds. |
| `reconnect_max_delay` | `float` | `5.0` | Maximum reconnect backoff in seconds. |
| `sample_rate_limit_hz` | `float` | `0.0` | Maximum delivered rate; `0.0` disables rate limiting. |
| `deliver_samples_with_error_status` | `bool` | `False` | Deliver records with a device error status before applying the recovery policy. |
| `recovery_policy` | `RecoveryPolicy` | `RECONNECT` | Reconnect after recoverable failures or stop on the first fault. |
| `calibration_override` | `Calibration \| None` | `None` | Complete independently verified calibration; `None` discovers it from the sensor. |

`Calibration(counts_per_force_unit, counts_per_torque_unit, force_unit, torque_unit)` is immutable. Both counts must be finite and positive. A calibration override is complete; force or torque values cannot be overridden independently.

`SensorConfiguration(product_name, calibration, source, revision)` is immutable. `source` distinguishes sensor discovery from a caller override. `revision` changes when an effective configuration change is observed.

Validation occurs when `Config` and `queue_size` are passed to `Client`. `queue_size` must be greater than zero. `sensor_host` must contain a non-whitespace host, and both ports must be in `1..65535`. All five configured timeout and reconnect-delay values must be finite and greater than zero; `reconnect_max_delay` must be at least `reconnect_initial_delay`. `sample_rate_limit_hz` must be finite and non-negative. A calibration override must have finite positive counts and neither unit may be `UNKNOWN`.

The per-read timeout accepted by `samples()` must be finite, non-negative, and representable by the native monotonic clock; invalid values raise `ConfigurationError`. `wait_for_first_sample()` applies the same timeout validation.

## Samples

`Sample` is an immutable dataclass:

| Field | Type | Meaning |
| --- | --- | --- |
| `rdt_sequence` | `int` | RDT packet sequence number. |
| `ft_sequence` | `int` | force/torque acquisition sequence number. |
| `status` | `int` | ATI device status bit mask. |
| `raw_wrench` | six-element `tuple[int, ...]` | Original signed counts `(Fx, Fy, Fz, Tx, Ty, Tz)`. |
| `force` | three-element `tuple[float, ...]` | Scaled force in `force_unit`. |
| `torque` | three-element `tuple[float, ...]` | Scaled torque in `torque_unit`. |
| `force_unit` | `ForceUnit` | Sensor-configured force unit. |
| `torque_unit` | `TorqueUnit` | Sensor-configured torque unit. |
| `configuration_revision` | `int` | Configuration revision used to scale the sample. |
| `received_at_ns` | `int` | Monotonic receive timestamp in nanoseconds. |
| `wrench` | six-element `tuple[float, ...]` | Read-only property combining `force` and `torque`. |

The values are ordinary tuples. NumPy is optional and can consume them explicitly with `numpy.asarray(sample.wrench)`.

## Health

`Health` is an immutable point-in-time snapshot. `Health.empty(sensor_host, rdt_port)` constructs a stopped zero-counter snapshot for application initialization and testing.

Identity and state fields are `state`, `fault_code`, `sensor_host`, `rdt_port`, and optional `sensor_configuration`. Progress fields are optional `last_rdt_sequence`, optional `last_ft_sequence`, `last_status`, `last_ft_progress`, optional `last_record_age`, and `last_error`.

Rate fields are `receive_rate_hz` and `delivery_rate_hz`. Counters are `received_count`, `delivered_count`, `rate_limited_count`, `device_error_count`, `warning_count`, `lost_count`, `duplicate_count`, `out_of_order_count`, `malformed_count`, `reconnect_count`, `timeout_count`, `callback_error_count`, `ft_stall_count`, `ft_backward_count`, `ft_restart_count`, `calibration_change_count`, and `python_queue_dropped_count`.

`last_error` is diagnostic text, not a stable machine-readable interface. Branch on `state`, `fault_code`, and counters instead.

## Enumerations

All public enums derive from `str` and `Enum`, so their `.value` is stable and serializable.

- `ForceUnit`: `UNKNOWN`, `POUND_FORCE`, `NEWTON`, `KILO_POUND_FORCE`, `KILO_NEWTON`, `KILOGRAM_FORCE`.
- `TorqueUnit`: `UNKNOWN`, `POUND_FORCE_INCH`, `POUND_FORCE_FOOT`, `NEWTON_METER`, `NEWTON_MILLIMETER`, `KILOGRAM_FORCE_CENTIMETER`, `KILO_NEWTON_METER`.
- `CalibrationSource`: `SENSOR`, `OVERRIDE`.
- `RecoveryPolicy`: `RECONNECT`, `FAIL_STOP`.
- `ClientState`: `STOPPED`, `CONNECTING`, `STREAMING`, `BACKOFF`, `FAULTED`.
- `FaultCode`: `NONE`, `SENSOR_CONFIGURATION`, `TIMEOUT`, `SOCKET`, `SERIOUS_STATUS`, `FT_STALL`, `FT_BACKWARD`, `MALFORMED_STORM`, `CALLBACK`.

## Exceptions

The public hierarchy is:

```text
NetFTError
├── ConfigurationError (also ValueError)
├── DiscoveryError (also ConnectionError)
├── NotConnectedError (also ConnectionError)
├── SensorFaultError
└── CallbackError
```

`ConfigurationError` reports invalid configuration or operation parameters. `DiscoveryError` reports HTTP configuration-discovery failure. `NotConnectedError` reports an operation that requires a running connection.

`SensorFaultError.fault_code` is the structured `FaultCode`, and `SensorFaultError.health` is the final `Health` snapshot. `CallbackError.__cause__` retains the exception raised by the callback or dispatcher. Exception message text is diagnostic and can change; applications should use the structured attributes and types.

## Deprecated compatibility API

`NetFT` and `Response` remain available through all 2.x releases and are scheduled for removal in 3.0. Constructing `NetFT` emits `DeprecationWarning`; using a non-default `num_samples` also warns because the native client uses a continuous stream.

`NetFT(host, port=49152, num_samples=1, count_per_force=None, count_per_torque=None)` discovers calibration when both count arguments are omitted. Providing both creates an override in newtons and newton-millimeters; providing only one raises `ValueError`.

Its methods are `connect()`, `disconnect()`, `bias()`, `get_data()`, `get_converted_data()`, and `start_streaming(duration=10, delay=0.1, print_data=True)`. Reading or biasing before `connect()` raises `ConnectionError`. `Response` has mutable `rdt_sequence`, `ft_sequence`, `status`, and list-valued `FTData` fields.

See the [2.0 migration guide](https://github.com/netft/pyNetFT/blob/main/docs/migration-2.md) for exact replacements.
