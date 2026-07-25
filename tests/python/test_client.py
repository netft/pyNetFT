from __future__ import annotations

from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fake_native import FakeReadResult

from pynetft import (
    Calibration,
    CalibrationSource,
    Client,
    ClientState,
    Config,
    ConfigurationError,
    DiscoveryError,
    FaultCode,
    ForceUnit,
    NotConnectedError,
    RecoveryPolicy,
    SensorFaultError,
    TorqueUnit,
    _native,
)


def test_config_is_explicitly_converted_to_native(fake_client_factory) -> None:
    calibration = Calibration(
        counts_per_force_unit=1_000_000.5,
        counts_per_torque_unit=2_000_000.25,
        force_unit=ForceUnit.KILOGRAM_FORCE,
        torque_unit=TorqueUnit.NEWTON_MILLIMETER,
    )
    config = Config(
        sensor_host="192.0.2.1",
        rdt_port=1234,
        http_port=8080,
        receive_timeout=0.2,
        configuration_connect_timeout=0.3,
        configuration_timeout=0.4,
        reconnect_initial_delay=0.5,
        reconnect_max_delay=0.6,
        sample_rate_limit_hz=500.0,
        deliver_samples_with_error_status=True,
        recovery_policy=RecoveryPolicy.FAIL_STOP,
        calibration_override=calibration,
    )

    client = Client(config, queue_size=4)
    native = fake_client_factory.instance.config

    assert native is not config
    assert native.sensor_host == config.sensor_host
    assert native.rdt_port == config.rdt_port
    assert native.http_port == config.http_port
    assert native.receive_timeout == pytest.approx(config.receive_timeout)
    assert native.configuration_connect_timeout == pytest.approx(
        config.configuration_connect_timeout
    )
    assert native.configuration_timeout == pytest.approx(config.configuration_timeout)
    assert native.reconnect_initial_delay == pytest.approx(config.reconnect_initial_delay)
    assert native.reconnect_max_delay == pytest.approx(config.reconnect_max_delay)
    assert native.sample_rate_limit_hz == pytest.approx(config.sample_rate_limit_hz)
    assert native.deliver_samples_with_error_status is config.deliver_samples_with_error_status
    assert native.recovery_policy == _native.RecoveryPolicy.FAIL_STOP
    assert native.calibration_override is not calibration
    assert native.calibration_override.counts_per_force_unit == pytest.approx(
        calibration.counts_per_force_unit
    )
    assert native.calibration_override.counts_per_torque_unit == pytest.approx(
        calibration.counts_per_torque_unit
    )
    assert native.calibration_override.force_unit == _native.ForceUnit.KILOGRAM_FORCE
    assert native.calibration_override.torque_unit == _native.TorqueUnit.NEWTON_MILLIMETER
    assert fake_client_factory.instance.queue_size == 4
    assert client is not None


def test_none_calibration_override_is_explicitly_converted(fake_client_factory) -> None:
    Client(Config(calibration_override=None))
    assert fake_client_factory.instance.config.calibration_override is None


def test_queue_capacity_validation_is_delegated_and_translated() -> None:
    with pytest.raises(ConfigurationError) as captured:
        Client(Config(), queue_size=0)
    assert isinstance(captured.value.__cause__, _native.ValidationError)


def test_context_starts_and_stops(fake_client_factory) -> None:
    with Client(Config()) as client:
        assert fake_client_factory.instance.started
        assert client is not None
    assert fake_client_factory.instance.stopped


def test_context_stops_when_body_raises(fake_client_factory) -> None:
    with pytest.raises(RuntimeError, match="sentinel"), Client(Config()):
        raise RuntimeError("sentinel")
    assert fake_client_factory.instance.stopped


def test_start_and_stop_are_idempotent(fake_client_factory) -> None:
    client = Client(Config())
    client.start()
    client.start()
    client.stop()
    client.stop()
    assert fake_client_factory.instance.start_count == 1
    assert fake_client_factory.instance.stop_count == 1


def test_start_failure_is_translated_and_can_be_retried(fake_client_factory) -> None:
    client = Client(Config())
    native = fake_client_factory.instance
    native.start_error = _native.DiscoveryError("missing sensor")

    with pytest.raises(DiscoveryError) as captured:
        client.start()
    assert captured.value.__cause__ is native.start_error

    native.start_error = None
    client.start()
    assert native.started
    client.stop()


def test_bias_delegates_and_translates_not_connected(fake_client_factory) -> None:
    client = Client(Config())
    with pytest.raises(NotConnectedError) as captured:
        client.bias()
    assert isinstance(captured.value.__cause__, _native.NotConnectedError)

    client.start()
    client.bias()
    assert fake_client_factory.instance.bias_count == 1
    client.stop()


def test_wait_for_first_sample_delegates(fake_client_factory, native_sample) -> None:
    client = Client(Config())
    client.start()
    assert not client.wait_for_first_sample(timeout=0.001)
    fake_client_factory.instance.queue(native_sample)
    assert client.wait_for_first_sample(timeout=0.1)
    client.stop()


def test_samples_returns_converted_sample(fake_client_factory, native_sample) -> None:
    client = Client(Config())
    with client:
        fake_client_factory.instance.queue(native_sample)
        sample = next(client.samples(timeout=0.1))
    assert sample.rdt_sequence == 11
    assert sample.ft_sequence == 12
    assert sample.status == 0x10
    assert sample.raw_wrench == (1, 2, 3, 4, 5, 6)
    assert all(type(value) is int for value in sample.raw_wrench)
    assert sample.force == (1.5, 2.5, 3.5)
    assert sample.torque == (4.5, 5.5, 6.5)
    assert sample.force_unit is ForceUnit.NEWTON
    assert sample.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert sample.configuration_revision == 7
    assert sample.received_at_ns == 123_456_789


@pytest.mark.parametrize("public_unit", list(ForceUnit))
def test_every_force_unit_converts_by_name(
    fake_client_factory, native_sample, public_unit: ForceUnit
) -> None:
    client = Client(Config())
    native_sample.force_unit = getattr(_native.ForceUnit, public_unit.name)
    with client:
        fake_client_factory.instance.queue(native_sample)
        assert next(client.samples(timeout=0.1)).force_unit is public_unit


@pytest.mark.parametrize("public_unit", list(TorqueUnit))
def test_every_torque_unit_including_newton_millimeter_converts_by_name(
    fake_client_factory, native_sample, public_unit: TorqueUnit
) -> None:
    client = Client(Config())
    native_sample.torque_unit = getattr(_native.TorqueUnit, public_unit.name)
    with client:
        fake_client_factory.instance.queue(native_sample)
        assert next(client.samples(timeout=0.1)).torque_unit is public_unit


def test_iterator_timeout_raises_builtin_timeout(fake_client_factory) -> None:
    with Client(Config()) as client, pytest.raises(TimeoutError):
        next(client.samples(timeout=0.001))


def test_stop_ends_iterator(fake_client_factory) -> None:
    client = Client(Config())
    client.start()
    iterator = client.samples()
    client.stop()
    with pytest.raises(StopIteration):
        next(iterator)


def test_stop_unblocks_an_active_iterator(fake_client_factory) -> None:
    client = Client(Config())
    client.start()
    iterator = client.samples()
    outcomes: list[str] = []

    def consume() -> None:
        try:
            next(iterator)
        except StopIteration:
            outcomes.append("closed")

    reader = Thread(target=consume)
    reader.start()
    assert fake_client_factory.instance.wait_until_read()
    client.stop()
    reader.join(1.0)

    assert not reader.is_alive()
    assert outcomes == ["closed"]


def test_stale_iterator_does_not_consume_from_a_restart(fake_client_factory, native_sample) -> None:
    client = Client(Config())
    client.start()
    native = fake_client_factory.instance
    native.pause_next_read_after_wake()
    stale_iterator = client.samples()
    outcomes: list[str] = []

    def consume_stale_iterator() -> None:
        try:
            next(stale_iterator)
        except StopIteration:
            outcomes.append("closed")

    stale_reader = Thread(target=consume_stale_iterator)
    stale_reader.start()
    assert native.wait_until_read()
    client.stop()
    assert native.wait_until_read_paused()
    client.start()
    native.queue(native_sample)
    native.release_paused_read()
    stale_reader.join(1.0)

    assert not stale_reader.is_alive()
    assert outcomes == ["closed"]
    assert next(client.samples(timeout=0.1)).rdt_sequence == 11
    client.stop()


def test_stop_after_native_read_prevents_a_late_sample(
    fake_client_factory, native_sample, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Client(Config())
    client.start()
    iterator = client.samples()

    def stop_then_return_sample(_: float | None) -> FakeReadResult:
        client.stop()
        return FakeReadResult(_native.ReadStatus.SAMPLE, native_sample)

    monkeypatch.setattr(fake_client_factory.instance, "read", stop_then_return_sample)
    with pytest.raises(StopIteration):
        next(iterator)


def test_closed_native_read_ends_iterator(fake_client_factory) -> None:
    client = Client(Config())
    client.start()
    fake_client_factory.instance.stop()
    with pytest.raises(StopIteration):
        next(client.samples())
    client.stop()


def test_faulted_close_raises_structured_fault(fake_client_factory, native_health) -> None:
    client = Client(Config())
    native = fake_client_factory.instance
    client.start()
    native.health_value = native_health
    native.faulted_value = True
    native.fault_code_value = _native.FaultCode.TIMEOUT
    native.stop()

    with pytest.raises(SensorFaultError) as captured:
        next(client.samples())

    assert captured.value.fault_code is FaultCode.TIMEOUT
    assert captured.value.health.state is ClientState.FAULTED
    assert captured.value.health.fault_code is FaultCode.TIMEOUT

    native.faulted_value = False
    client.start()
    assert native.start_count == 2
    client.stop()


def test_fault_snapshot_and_stop_are_serialized_with_restart(
    fake_client_factory, native_health, native_sample
) -> None:
    client = Client(Config())
    native = fake_client_factory.instance
    client.start()
    native.health_value = native_health
    native.faulted_value = True
    native.fault_code_value = _native.FaultCode.TIMEOUT
    native.dropped_value = 17
    native.pause_fault_inspection()
    native.stop()

    old_errors: list[SensorFaultError] = []
    old_closed = Event()

    def consume_old_fault() -> None:
        try:
            next(client.samples())
        except SensorFaultError as error:
            old_errors.append(error)
        except StopIteration:
            old_closed.set()

    old_reader = Thread(target=consume_old_fault)
    old_reader.start()
    assert native.wait_until_fault_inspection()

    restart_attempted = Event()
    restart_finished = Event()

    def restart_and_queue() -> None:
        restart_attempted.set()
        client.stop()
        native.faulted_value = False
        native.fault_code_value = _native.FaultCode.NONE
        native.health_value = SimpleNamespace(
            **{
                **vars(native_health),
                "state": _native.ClientState.STREAMING,
                "fault_code": _native.FaultCode.NONE,
                "last_error": "",
            }
        )
        client.start()
        native.dropped_value = 99
        native.queue(native_sample)
        restart_finished.set()

    restarter = Thread(target=restart_and_queue)
    restarter.start()
    assert restart_attempted.wait(1.0)

    try:
        assert client._lock.locked()
        assert not restart_finished.is_set()
    finally:
        native.release_fault_inspection()

    old_reader.join(1.0)
    restarter.join(1.0)
    assert not old_reader.is_alive()
    assert not restarter.is_alive()
    assert not old_closed.is_set()
    assert len(old_errors) == 1
    assert old_errors[0].fault_code is FaultCode.TIMEOUT
    assert old_errors[0].health.fault_code is FaultCode.TIMEOUT
    assert old_errors[0].health.state is ClientState.FAULTED
    assert old_errors[0].health.python_queue_dropped_count == 17
    assert next(client.samples(timeout=0.1)).rdt_sequence == 11
    client.stop()


def test_latest_sample_is_converted_or_none(fake_client_factory, native_sample) -> None:
    client = Client(Config())
    assert client.latest_sample() is None
    client.start()
    fake_client_factory.instance.queue(native_sample)
    sample = client.latest_sample()
    assert sample is not None
    assert sample.raw_wrench == (1, 2, 3, 4, 5, 6)
    client.stop()


def test_health_snapshot_converts_every_field(fake_client_factory, native_health) -> None:
    client = Client(Config())
    native = fake_client_factory.instance
    native.health_value = native_health
    native.dropped_value = 17

    health = client.health()

    assert health.state is ClientState.FAULTED
    assert health.fault_code is FaultCode.TIMEOUT
    assert health.sensor_host == "192.0.2.1"
    assert health.rdt_port == 49153
    assert health.sensor_configuration is not None
    assert health.sensor_configuration.product_name == "Net F/T"
    assert health.sensor_configuration.calibration.force_unit is ForceUnit.NEWTON
    assert health.sensor_configuration.calibration.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert health.sensor_configuration.source is CalibrationSource.SENSOR
    assert health.sensor_configuration.revision == 9
    expected_tail = (
        101,
        102,
        0x20,
        7000.5,
        3500.25,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        0.125,
        "timed out",
        "forward",
        17,
    )
    assert (
        health.last_rdt_sequence,
        health.last_ft_sequence,
        health.last_status,
        health.receive_rate_hz,
        health.delivery_rate_hz,
        health.received_count,
        health.delivered_count,
        health.rate_limited_count,
        health.device_error_count,
        health.warning_count,
        health.lost_count,
        health.duplicate_count,
        health.out_of_order_count,
        health.malformed_count,
        health.reconnect_count,
        health.timeout_count,
        health.callback_error_count,
        health.ft_stall_count,
        health.ft_backward_count,
        health.ft_restart_count,
        health.calibration_change_count,
        health.last_record_age,
        health.last_error,
        health.last_ft_progress,
        health.python_queue_dropped_count,
    ) == expected_tail


def test_health_without_sensor_configuration_converts_none(
    fake_client_factory, native_health
) -> None:
    client = Client(Config())
    native_health.sensor_configuration = None
    fake_client_factory.instance.health_value = native_health
    assert client.health().sensor_configuration is None


def test_native_validation_errors_are_configuration_errors(
    fake_client_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Client(Config())

    def reject_timeout(_: float) -> bool:
        raise _native.ValidationError("invalid timeout")

    monkeypatch.setattr(fake_client_factory.instance, "wait_for_first_sample", reject_timeout)
    with pytest.raises(ConfigurationError) as captured:
        client.wait_for_first_sample(-1.0)
    assert isinstance(captured.value.__cause__, _native.ValidationError)


def test_running_iterator_rejects_callback_change(fake_client_factory) -> None:
    client = Client(Config())
    client.start()
    with pytest.raises(RuntimeError):
        client.start(lambda _: None)
    client.stop()


def test_constructor_callback_cannot_be_consumed_as_iterator(
    fake_client_factory,
) -> None:
    client = Client(Config(), callback=lambda _: None)
    with pytest.raises(RuntimeError):
        client.samples()
