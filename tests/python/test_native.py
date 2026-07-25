import math
import socket
import sys
import threading
import time

import pytest

from pynetft import _native


def test_native_config_uses_core_defaults() -> None:
    config = _native.Config()
    assert config.sensor_host == "192.168.1.1"
    assert config.rdt_port == 49152


def test_native_client_rejects_zero_queue_size() -> None:
    with pytest.raises(ValueError):
        _native.NativeClient(_native.Config(), 0)


def test_read_status_values_are_distinct() -> None:
    assert _native.ReadStatus.SAMPLE is not _native.ReadStatus.TIMEOUT
    assert _native.ReadStatus.TIMEOUT is not _native.ReadStatus.CLOSED


def test_native_enum_members_match_the_conversion_boundary() -> None:
    expected_members = {
        "ForceUnit": {
            "UNKNOWN",
            "POUND_FORCE",
            "NEWTON",
            "KILO_POUND_FORCE",
            "KILO_NEWTON",
            "KILOGRAM_FORCE",
        },
        "TorqueUnit": {
            "UNKNOWN",
            "POUND_FORCE_INCH",
            "POUND_FORCE_FOOT",
            "NEWTON_METER",
            "NEWTON_MILLIMETER",
            "KILOGRAM_FORCE_CENTIMETER",
            "KILO_NEWTON_METER",
        },
        "CalibrationSource": {"SENSOR", "OVERRIDE"},
        "RecoveryPolicy": {"RECONNECT", "FAIL_STOP"},
        "ClientState": {
            "STOPPED",
            "CONNECTING",
            "STREAMING",
            "BACKOFF",
            "FAULTED",
        },
        "FaultCode": {
            "NONE",
            "SENSOR_CONFIGURATION",
            "TIMEOUT",
            "SOCKET",
            "SERIOUS_STATUS",
            "FT_STALL",
            "FT_BACKWARD",
            "MALFORMED_STORM",
            "CALLBACK",
        },
        "StatusSeverity": {"OK", "WARN", "ERROR"},
    }

    for enum_name, members in expected_members.items():
        assert set(getattr(_native, enum_name).__members__) == members


def test_native_configuration_values_round_trip() -> None:
    calibration = _native.Calibration()
    calibration.counts_per_force_unit = 1_000_000.0
    calibration.counts_per_torque_unit = 2_000_000.0
    calibration.force_unit = _native.ForceUnit.NEWTON
    calibration.torque_unit = _native.TorqueUnit.NEWTON_MILLIMETER

    sensor_configuration = _native.SensorConfiguration()
    sensor_configuration.product_name = "Net F/T"
    sensor_configuration.calibration = calibration
    sensor_configuration.source = _native.CalibrationSource.OVERRIDE
    sensor_configuration.revision = 7

    config = _native.Config()
    config.receive_timeout = 0.2
    config.configuration_connect_timeout = 0.3
    config.configuration_timeout = 0.4
    config.reconnect_initial_delay = 0.5
    config.reconnect_max_delay = 0.6
    config.recovery_policy = _native.RecoveryPolicy.FAIL_STOP
    config.calibration_override = calibration

    assert sensor_configuration.calibration.force_unit == _native.ForceUnit.NEWTON
    assert sensor_configuration.revision == 7
    assert config.receive_timeout == pytest.approx(0.2)
    assert config.configuration_connect_timeout == pytest.approx(0.3)
    assert config.configuration_timeout == pytest.approx(0.4)
    assert config.reconnect_initial_delay == pytest.approx(0.5)
    assert config.reconnect_max_delay == pytest.approx(0.6)
    assert config.calibration_override is not None
    assert config.calibration_override.counts_per_torque_unit == 2_000_000.0


def test_native_sample_health_and_read_results_are_read_only() -> None:
    sample = _native.Sample()
    health = _native.Health()
    result = _native.ReadResult()

    assert sample.raw_wrench == [0, 0, 0, 0, 0, 0]
    assert sample.received_at_ns == 0
    assert health.last_record_age is None
    assert result.status == _native.ReadStatus.TIMEOUT
    assert result.sample is None
    with pytest.raises(AttributeError):
        sample.status = 1
    with pytest.raises(AttributeError):
        health.sensor_host = "changed"
    with pytest.raises(AttributeError):
        result.sample = sample


def test_native_exceptions_have_explicit_python_bases() -> None:
    assert issubclass(_native.ValidationError, ValueError)
    assert issubclass(_native.NotConnectedError, ConnectionError)
    assert issubclass(_native.DiscoveryError, ConnectionError)

    client = _native.NativeClient(_native.Config(), 1)
    with pytest.raises(_native.NotConnectedError):
        client.bias()


def test_prestart_read_is_closed_and_stop_is_idempotent() -> None:
    client = _native.NativeClient(_native.Config(), 1)
    assert client.read(None).status == _native.ReadStatus.CLOSED
    client.stop()
    client.stop()
    assert client.read(0.0).status == _native.ReadStatus.CLOSED


def test_native_waits_reject_invalid_timeouts() -> None:
    client = _native.NativeClient(_native.Config(), 1)
    with pytest.raises(_native.ValidationError):
        client.read(-1.0)
    with pytest.raises(_native.ValidationError):
        client.read(math.inf)
    with pytest.raises(_native.ValidationError):
        client.wait_for_first_sample(math.nan)
    with pytest.raises(_native.ValidationError):
        client.wait_for_first_sample(-1.0)
    with pytest.raises(_native.ValidationError):
        client.read(sys.float_info.max)
    with pytest.raises(_native.ValidationError):
        client.wait_for_first_sample(sys.float_info.max)


def test_native_client_destruction_releases_the_gil_while_stopping() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(2.0)
    accepted = threading.Event()
    release_connection = threading.Event()

    def hold_configuration_connection() -> None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        with connection:
            accepted.set()
            release_connection.wait(2.0)

    server = threading.Thread(target=hold_configuration_connection)
    server.start()

    owner = []
    destroyer = None
    destruction_started = threading.Event()
    destruction_finished = threading.Event()

    def destroy_last_reference() -> None:
        value = owner.pop()
        destruction_started.set()
        del value
        destruction_finished.set()

    progress_iterations = 0
    try:
        config = _native.Config()
        config.sensor_host = "127.0.0.1"
        config.http_port = listener.getsockname()[1]
        config.configuration_connect_timeout = 0.2
        config.configuration_timeout = 0.5
        config.recovery_policy = _native.RecoveryPolicy.FAIL_STOP
        client = _native.NativeClient(config, 1)
        client.start()
        assert accepted.wait(1.0)
        owner.append(client)
        del client

        destroyer = threading.Thread(target=destroy_last_reference)
        destroyer.start()
        assert destruction_started.wait(1.0)
        deadline = time.monotonic() + 2.0
        while not destruction_finished.is_set() and time.monotonic() < deadline:
            progress_iterations += 1
            time.sleep(0)
        assert destruction_finished.is_set()
    finally:
        release_connection.set()
        listener.close()
        if destroyer is not None:
            destroyer.join(2.0)
        if owner:
            owner.pop().stop()
        server.join(2.0)

    assert not owner
    assert destroyer is not None
    assert not destroyer.is_alive()
    assert not server.is_alive()
    assert progress_iterations >= 10


def test_near_clock_limit_first_sample_wait_remains_stoppable() -> None:
    calibration = _native.Calibration()
    calibration.counts_per_force_unit = 1.0
    calibration.counts_per_torque_unit = 1.0
    calibration.force_unit = _native.ForceUnit.NEWTON
    calibration.torque_unit = _native.TorqueUnit.NEWTON_MILLIMETER
    config = _native.Config()
    config.sensor_host = "192.0.2.1"
    config.receive_timeout = 0.02
    config.reconnect_initial_delay = 0.01
    config.reconnect_max_delay = 0.01
    config.calibration_override = calibration
    client = _native.NativeClient(config, 1)
    client.start()

    def stop_client() -> None:
        time.sleep(0.1)
        client.stop()

    stopper = threading.Thread(target=stop_client)
    stopper.start()
    started = time.monotonic()
    near_clock_limit = math.nextafter((2**63 - 1) / 1_000_000_000, 0.0)
    received_sample = client.wait_for_first_sample(near_clock_limit)
    elapsed = time.monotonic() - started
    stopper.join(2.0)

    assert not stopper.is_alive()
    assert not received_sample
    assert 0.08 <= elapsed < 2.0
