from __future__ import annotations

from http.client import HTTPConnection, RemoteDisconnected
from threading import (
    Event,
    Thread,
    current_thread,
)
from threading import (
    enumerate as enumerate_threads,
)
from time import monotonic

import pytest
from fake_sensor import (
    BIAS,
    START_REALTIME,
    STOP_STREAMING,
    FakeSensor,
)

from pynetft import (
    CalibrationSource,
    Client,
    Config,
    ForceUnit,
    TorqueUnit,
)


def test_http_handler_exception_is_raised_by_close() -> None:
    sensor = FakeSensor()
    connection = HTTPConnection(sensor.host, sensor.http_port, timeout=1.0)
    failure = RuntimeError("handler sentinel")

    def fail_response(path: str) -> tuple[int, bytes]:
        del path
        raise failure

    sensor._http_response = fail_response  # type: ignore[method-assign]
    try:
        connection.request("GET", "/netftapi2.xml")
        with pytest.raises(RemoteDisconnected):
            connection.getresponse()
        with pytest.raises(RuntimeError) as captured:
            sensor.close()
        assert captured.value is failure
    finally:
        connection.close()
        sensor.close()


def test_close_does_not_wait_for_a_blocked_http_handler() -> None:
    sensor = FakeSensor()
    connection = HTTPConnection(sensor.host, sensor.http_port, timeout=1.0)
    handler_entered = Event()
    release_handler = Event()
    request_finished = Event()
    close_finished = Event()
    request_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    second_close_errors: list[BaseException] = []
    handler_threads: list[Thread] = []
    original_response = sensor._http_response

    def blocked_response(path: str) -> tuple[int, bytes]:
        handler_threads.append(current_thread())
        handler_entered.set()
        release_handler.wait()
        return original_response(path)

    def request_configuration() -> None:
        try:
            connection.request("GET", "/netftapi2.xml")
            response = connection.getresponse()
            response.read()
        except BaseException as error:
            request_errors.append(error)
        finally:
            request_finished.set()

    def close_sensor() -> None:
        try:
            sensor.close()
        except BaseException as error:
            close_errors.append(error)
        finally:
            close_finished.set()

    sensor._http_response = blocked_response  # type: ignore[method-assign]
    requester = Thread(target=request_configuration, name="fake-http-request")
    closer = Thread(target=close_sensor, name="fake-sensor-close-watchdog")
    closer_started = False
    requester.start()
    try:
        assert handler_entered.wait(1.0)
        closer.start()
        closer_started = True
        assert close_finished.wait(1.0)
    finally:
        release_handler.set()
        if closer_started:
            closer.join(1.0)
        try:
            sensor.close()
        except BaseException as error:
            second_close_errors.append(error)
        requester.join(1.0)
        for handler_thread in handler_threads:
            handler_thread.join(1.0)
        connection.close()

    assert not closer.is_alive()
    assert not requester.is_alive()
    assert len(handler_threads) == 1
    assert not handler_threads[0].is_alive()
    assert request_finished.is_set()
    assert len(close_errors) == 1
    assert isinstance(close_errors[0], TimeoutError)
    assert second_close_errors == []
    assert request_errors == []
    assert [
        thread.name
        for thread in enumerate_threads()
        if not thread.daemon and thread.name.startswith("fake-netft-")
    ] == []


def test_second_close_surfaces_failure_from_a_late_http_handler() -> None:
    sensor = FakeSensor()
    connection = HTTPConnection(sensor.host, sensor.http_port, timeout=1.0)
    handler_entered = Event()
    release_handler = Event()
    close_finished = Event()
    request_errors: list[BaseException] = []
    first_close_errors: list[BaseException] = []
    cleanup_errors: list[BaseException] = []
    handler_threads: list[Thread] = []
    failure = RuntimeError("late handler sentinel")

    def blocked_failure(path: str) -> tuple[int, bytes]:
        del path
        handler_threads.append(current_thread())
        handler_entered.set()
        release_handler.wait()
        raise failure

    def request_configuration() -> None:
        try:
            connection.request("GET", "/netftapi2.xml")
            connection.getresponse()
        except BaseException as error:
            request_errors.append(error)

    def close_sensor() -> None:
        try:
            sensor.close()
        except BaseException as error:
            first_close_errors.append(error)
        finally:
            close_finished.set()

    sensor._http_response = blocked_failure  # type: ignore[method-assign]
    requester = Thread(target=request_configuration, name="late-http-request")
    closer = Thread(target=close_sensor, name="late-handler-close-watchdog")
    closer_started = False
    requester.start()
    try:
        assert handler_entered.wait(1.0)
        closer.start()
        closer_started = True
        assert close_finished.wait(1.0)
        assert len(first_close_errors) == 1
        assert isinstance(first_close_errors[0], TimeoutError)

        release_handler.set()
        with pytest.raises(RuntimeError) as captured:
            sensor.close()
        assert captured.value is failure
    finally:
        release_handler.set()
        if closer_started:
            closer.join(1.0)
        requester.join(1.0)
        for handler_thread in handler_threads:
            handler_thread.join(1.0)
        connection.close()
        try:
            sensor.close()
        except BaseException as error:
            cleanup_errors.append(error)

    assert not closer.is_alive()
    assert not requester.is_alive()
    assert len(handler_threads) == 1
    assert not handler_threads[0].is_alive()
    assert len(request_errors) == 1
    assert isinstance(request_errors[0], RemoteDisconnected)
    assert cleanup_errors == []


def test_repeated_close_is_clean_after_an_ordinary_http_request() -> None:
    sensor = FakeSensor()
    connection = HTTPConnection(sensor.host, sensor.http_port, timeout=1.0)
    try:
        connection.request("GET", "/netftapi2.xml")
        response = connection.getresponse()
        response.read()
        sensor.close()
        sensor.close()
    finally:
        connection.close()
        sensor.close()

    assert not sensor._http_thread.is_alive()
    assert not sensor._udp_thread.is_alive()
    with sensor._condition:
        assert sensor._active_http_handlers == set()


def test_discovers_units_and_delivers_raw_and_scaled_values(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.configure(
        product_name="ATI Mini45",
        counts_per_force=1_000_000,
        counts_per_torque=1_000,
        force_unit="N",
        torque_unit="N-mm",
    )
    fake_sensor.queue_record((1_000_000, -2_000_000, 3_000_000, 1_000, -2_000, 3_000))

    config = Config(
        sensor_host=fake_sensor.host,
        rdt_port=fake_sensor.rdt_port,
        http_port=fake_sensor.http_port,
    )
    with Client(config) as client:
        sample = next(client.samples(timeout=1.0))
        health = client.health()

    assert sample.raw_wrench == (
        1_000_000,
        -2_000_000,
        3_000_000,
        1_000,
        -2_000,
        3_000,
    )
    assert sample.force == (1.0, -2.0, 3.0)
    assert sample.torque == (1.0, -2.0, 3.0)
    assert sample.force_unit is ForceUnit.NEWTON
    assert sample.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert sample.rdt_sequence == 1
    assert sample.ft_sequence == 1
    assert sample.status == 0
    assert sample.configuration_revision == 1
    assert sample.received_at_ns > 0

    sensor_configuration = health.sensor_configuration
    assert sensor_configuration is not None
    assert sensor_configuration.product_name == "ATI Mini45"
    assert sensor_configuration.source is CalibrationSource.SENSOR
    assert sensor_configuration.revision == 1
    assert sensor_configuration.calibration.counts_per_force_unit == 1_000_000
    assert sensor_configuration.calibration.counts_per_torque_unit == 1_000
    assert sensor_configuration.calibration.force_unit is ForceUnit.NEWTON
    assert sensor_configuration.calibration.torque_unit is TorqueUnit.NEWTON_MILLIMETER
    assert health.received_count == 1
    assert health.delivered_count == 1
    assert health.python_queue_dropped_count == 0
    assert fake_sensor.wait_for_command(STOP_STREAMING, timeout=1.0)
    assert fake_sensor.commands.count(START_REALTIME) == 1
    assert (0x1234, START_REALTIME, 0) in fake_sensor.requests
    assert (0x1234, STOP_STREAMING, 0) in fake_sensor.requests
    assert BIAS not in fake_sensor.commands


def test_reports_status_sequence_loss_and_queue_drops(
    fake_sensor: FakeSensor,
) -> None:
    fake_sensor.configure()
    fake_sensor.queue_record(
        (10, 20, 30, 40, 50, 60),
        rdt_sequence=10,
        ft_sequence=100,
    )

    config = Config(
        sensor_host=fake_sensor.host,
        rdt_port=fake_sensor.rdt_port,
        http_port=fake_sensor.http_port,
    )
    with Client(config, queue_size=1) as client:
        assert client.wait_for_first_sample(timeout=1.0)
        fake_sensor.queue_record(
            (-10, -20, -30, -40, -50, -60),
            rdt_sequence=13,
            ft_sequence=101,
            status=0x80010000,
        )

        deadline = monotonic() + 1.0
        while (latest := client.latest_sample()) is None or latest.rdt_sequence != 13:
            remaining = deadline - monotonic()
            assert remaining > 0.0

        sample = next(client.samples(timeout=1.0))
        health = client.health()

    assert sample.rdt_sequence == 13
    assert sample.ft_sequence == 101
    assert sample.status == 0x80010000
    assert sample.raw_wrench == (-10, -20, -30, -40, -50, -60)
    assert health.last_rdt_sequence == 13
    assert health.last_ft_sequence == 101
    assert health.last_status == 0x80010000
    assert health.received_count == 2
    assert health.delivered_count == 2
    assert health.lost_count == 2
    assert health.warning_count == 1
    assert health.device_error_count == 0
    assert health.python_queue_dropped_count == 1
    assert health.last_ft_progress == "forward"
    assert health.last_record_age is not None
    assert health.last_record_age >= 0.0
    assert BIAS not in fake_sensor.commands
