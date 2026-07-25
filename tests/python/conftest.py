from __future__ import annotations

from types import SimpleNamespace

import pytest
from fake_native import FakeNativeClient

from pynetft import _native


class FakeNativeFactory:
    def __init__(self) -> None:
        self.instance: FakeNativeClient

    def __call__(self, config: object, queue_size: int) -> FakeNativeClient:
        self.instance = FakeNativeClient(config, queue_size)
        return self.instance


@pytest.fixture
def fake_client_factory(monkeypatch: pytest.MonkeyPatch) -> FakeNativeFactory:
    from pynetft import client

    factory = FakeNativeFactory()
    monkeypatch.setattr(client._native, "NativeClient", factory)
    return factory


@pytest.fixture
def native_sample() -> SimpleNamespace:
    return SimpleNamespace(
        rdt_sequence=11,
        ft_sequence=12,
        status=0x10,
        raw_wrench=[1, 2, 3, 4, 5, 6],
        force=[1.5, 2.5, 3.5],
        torque=[4.5, 5.5, 6.5],
        force_unit=_native.ForceUnit.NEWTON,
        torque_unit=_native.TorqueUnit.NEWTON_MILLIMETER,
        configuration_revision=7,
        received_at_ns=123_456_789,
    )


@pytest.fixture
def native_health() -> SimpleNamespace:
    calibration = SimpleNamespace(
        counts_per_force_unit=1_000_000.0,
        counts_per_torque_unit=2_000_000.0,
        force_unit=_native.ForceUnit.NEWTON,
        torque_unit=_native.TorqueUnit.NEWTON_MILLIMETER,
    )
    sensor_configuration = SimpleNamespace(
        product_name="Net F/T",
        calibration=calibration,
        source=_native.CalibrationSource.SENSOR,
        revision=9,
    )
    values = {
        "state": _native.ClientState.FAULTED,
        "fault_code": _native.FaultCode.TIMEOUT,
        "sensor_host": "192.0.2.1",
        "rdt_port": 49153,
        "sensor_configuration": sensor_configuration,
        "last_rdt_sequence": 101,
        "last_ft_sequence": 102,
        "last_status": 0x20,
        "receive_rate_hz": 7000.5,
        "delivery_rate_hz": 3500.25,
        "received_count": 1,
        "delivered_count": 2,
        "rate_limited_count": 3,
        "device_error_count": 4,
        "warning_count": 5,
        "lost_count": 6,
        "duplicate_count": 7,
        "out_of_order_count": 8,
        "malformed_count": 9,
        "reconnect_count": 10,
        "timeout_count": 11,
        "callback_error_count": 12,
        "ft_stall_count": 13,
        "ft_backward_count": 14,
        "ft_restart_count": 15,
        "calibration_change_count": 16,
        "last_record_age": 0.125,
        "last_error": "timed out",
        "last_ft_progress": "forward",
    }
    return SimpleNamespace(**values)
