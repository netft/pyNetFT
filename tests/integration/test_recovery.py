from __future__ import annotations

import pytest
from fake_sensor import BIAS, START_REALTIME, FakeSensor

from pynetft import (
    CalibrationSource,
    Client,
    ClientState,
    Config,
    FaultCode,
    ForceUnit,
    RecoveryPolicy,
    SensorFaultError,
    TorqueUnit,
)


def _config(
    sensor: FakeSensor,
    *,
    recovery_policy: RecoveryPolicy = RecoveryPolicy.RECONNECT,
) -> Config:
    return Config(
        sensor_host=sensor.host,
        rdt_port=sensor.rdt_port,
        http_port=sensor.http_port,
        receive_timeout=0.05,
        configuration_connect_timeout=0.2,
        configuration_timeout=0.2,
        reconnect_initial_delay=0.01,
        reconnect_max_delay=0.02,
        recovery_policy=recovery_policy,
    )


def _assert_fault(sensor: FakeSensor, expected: FaultCode) -> SensorFaultError:
    client = Client(_config(sensor, recovery_policy=RecoveryPolicy.FAIL_STOP))
    with pytest.raises(SensorFaultError) as captured, client:
        next(client.samples(timeout=1.0))
    assert captured.value.fault_code is expected
    assert captured.value.health.fault_code is expected
    assert captured.value.health.state is ClientState.FAULTED
    assert BIAS not in sensor.commands
    return captured.value


def test_http_discovery_failure_is_a_structured_sensor_fault(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.respond_to_http_with(503)

    error = _assert_fault(fake_sensor, FaultCode.SENSOR_CONFIGURATION)

    assert error.health.sensor_configuration is None
    assert error.health.reconnect_count == 0
    assert error.health.received_count == 0
    assert fake_sensor.http_request_count == 1
    assert START_REALTIME not in fake_sensor.commands


def test_receive_timeout_reconnects_and_resumes_streaming(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.configure(product_name="reconnect-sensor")
    fake_sensor.queue_record(
        (1, 2, 3, 4, 5, 6),
        rdt_sequence=20,
        ft_sequence=30,
        on_start=2,
    )

    with Client(_config(fake_sensor)) as client:
        sample = next(client.samples(timeout=1.0))
        health = client.health()

    assert sample.rdt_sequence == 20
    assert sample.ft_sequence == 30
    assert sample.configuration_revision == 1
    assert health.state is ClientState.STREAMING
    assert health.timeout_count >= 1
    assert health.reconnect_count >= 1
    assert health.calibration_change_count == 0
    assert health.sensor_configuration is not None
    assert health.sensor_configuration.product_name == "reconnect-sensor"
    assert health.sensor_configuration.source is CalibrationSource.SENSOR
    assert fake_sensor.commands.count(START_REALTIME) >= 2
    assert fake_sensor.http_request_count >= 2
    assert BIAS not in fake_sensor.commands


def test_receive_timeout_fail_stop_reports_timeout_fault(
    fake_sensor: FakeSensor,
) -> None:
    error = _assert_fault(fake_sensor, FaultCode.TIMEOUT)

    assert error.health.timeout_count == 1
    assert error.health.reconnect_count == 0
    assert error.health.received_count == 0
    assert fake_sensor.commands.count(START_REALTIME) == 1


def test_malformed_packet_storm_reports_counter_and_fault(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.queue_malformed(repeat=10)

    error = _assert_fault(fake_sensor, FaultCode.MALFORMED_STORM)

    assert error.health.malformed_count == 10
    assert error.health.received_count == 0
    assert error.health.delivered_count == 0
    assert error.health.timeout_count == 0


def test_serious_status_reports_status_counter_and_fault(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.queue_record(
        (1, -2, 3, -4, 5, -6),
        rdt_sequence=50,
        ft_sequence=60,
        status=0x00000002,
    )

    error = _assert_fault(fake_sensor, FaultCode.SERIOUS_STATUS)

    assert error.health.last_rdt_sequence == 50
    assert error.health.last_ft_sequence == 60
    assert error.health.last_status == 0x00000002
    assert error.health.device_error_count == 1
    assert error.health.warning_count == 0
    assert error.health.received_count == 1
    assert error.health.delivered_count == 0


def test_ft_sequence_stall_reports_progress_counter_and_fault(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.queue_record(
        (1, 2, 3, 4, 5, 6),
        rdt_sequence=70,
        ft_sequence=80,
    )
    client = Client(
        _config(fake_sensor, recovery_policy=RecoveryPolicy.FAIL_STOP),
        queue_size=2,
    )
    with client:
        first = next(client.samples(timeout=1.0))
        fake_sensor.queue_record(
            (6, 5, 4, 3, 2, 1),
            rdt_sequence=71,
            ft_sequence=80,
        )
        stalled = next(client.samples(timeout=1.0))
        with pytest.raises(SensorFaultError) as captured:
            next(client.samples(timeout=1.0))

    assert first.ft_sequence == 80
    assert stalled.ft_sequence == 80
    assert stalled.rdt_sequence == 71
    assert captured.value.fault_code is FaultCode.FT_STALL
    assert captured.value.health.ft_stall_count == 1
    assert captured.value.health.last_ft_progress == "stall"
    assert captured.value.health.received_count == 2
    assert captured.value.health.delivered_count == 2
    assert BIAS not in fake_sensor.commands


def test_configuration_change_after_reconnect_increments_revision(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.configure(
        product_name="revision-sensor",
        counts_per_force=1_000,
        counts_per_torque=1_000,
        force_unit="N",
        torque_unit="N-m",
    )
    fake_sensor.configure_on_start(
        1,
        counts_per_force=2_000,
        counts_per_torque=4_000,
        torque_unit="N-mm",
    )
    fake_sensor.queue_record(
        (2_000, -4_000, 6_000, 4_000, -8_000, 12_000),
        rdt_sequence=90,
        ft_sequence=100,
        on_start=2,
    )

    with Client(_config(fake_sensor)) as client:
        sample = next(client.samples(timeout=1.0))
        health = client.health()

    assert sample.force == (1.0, -2.0, 3.0)
    assert sample.torque == (1.0, -2.0, 3.0)
    assert sample.force_unit is ForceUnit.NEWTON
    assert sample.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert sample.configuration_revision == 2
    assert health.calibration_change_count == 1
    assert health.timeout_count >= 1
    assert health.reconnect_count >= 1
    configuration = health.sensor_configuration
    assert configuration is not None
    assert configuration.product_name == "revision-sensor"
    assert configuration.source is CalibrationSource.SENSOR
    assert configuration.revision == 2
    assert configuration.calibration.counts_per_force_unit == 2_000
    assert configuration.calibration.counts_per_torque_unit == 4_000
    assert configuration.calibration.force_unit is ForceUnit.NEWTON
    assert configuration.calibration.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert fake_sensor.commands.count(START_REALTIME) >= 2
    assert BIAS not in fake_sensor.commands
