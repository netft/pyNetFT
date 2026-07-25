from __future__ import annotations

import importlib.util
from pathlib import Path
from time import monotonic, sleep
from types import ModuleType

import pytest
from fake_sensor import BIAS, START_REALTIME, STOP_STREAMING, FakeSensor

from pynetft import Config

ROOT = Path(__file__).resolve().parents[2]


def _load_hardware_tool() -> ModuleType:
    path = ROOT / "tools" / "hardware_test.py"
    specification = importlib.util.spec_from_file_location("hardware_test", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_sampling_window_starts_after_discovery_and_first_sample(
    fake_sensor: FakeSensor, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_hardware_tool()
    fake_sensor.configure(
        product_name="Test Sensor",
        counts_per_force=1_000_000,
        counts_per_torque=1_000,
        force_unit="N",
        torque_unit="N-mm",
    )
    fake_sensor.queue_record((1_000_000, -2_000_000, 3_000_000, 1_000, -2_000, 3_000))
    fake_sensor.queue_record((2_000_000, -3_000_000, 4_000_000, 2_000, -3_000, 4_000))
    fake_sensor.queue_record((3_000_000, -4_000_000, 5_000_000, 3_000, -4_000, 5_000))
    original_response = fake_sensor._http_response
    clock_calls: list[float] = []

    def slow_discovery(path: str) -> tuple[int, bytes]:
        sleep(0.02)
        return original_response(path)

    def streaming_clock() -> float:
        assert START_REALTIME in fake_sensor.commands
        value = monotonic()
        clock_calls.append(value)
        return value

    fake_sensor._http_response = slow_discovery  # type: ignore[method-assign]
    monkeypatch.setattr(tool, "monotonic", streaming_clock)
    started_at = monotonic()

    summary = tool.collect_hardware(
        Config(
            sensor_host=fake_sensor.host,
            rdt_port=fake_sensor.rdt_port,
            http_port=fake_sensor.http_port,
            receive_timeout=1.0,
        ),
        duration=0.05,
    )
    elapsed = monotonic() - started_at

    assert summary.sample_count >= 2
    assert summary.first_rdt_sequence != summary.last_rdt_sequence
    assert summary.first_ft_sequence != summary.last_ft_sequence
    assert summary.product_name == "Test Sensor"
    assert elapsed >= 0.07
    assert clock_calls
    assert fake_sensor.commands.count(START_REALTIME) == 1
    assert fake_sensor.wait_for_command(STOP_STREAMING, timeout=1.0)
    assert fake_sensor.commands.count(STOP_STREAMING) == 1
    assert BIAS not in fake_sensor.commands


def test_failed_hardware_validation_still_stops_without_bias(fake_sensor: FakeSensor) -> None:
    tool = _load_hardware_tool()
    fake_sensor.queue_record((1, 2, 3, 4, 5, 6))

    with pytest.raises(tool.HardwareValidationError):
        tool.collect_hardware(
            Config(
                sensor_host=fake_sensor.host,
                rdt_port=fake_sensor.rdt_port,
                http_port=fake_sensor.http_port,
            ),
            duration=0.02,
        )

    assert fake_sensor.commands.count(START_REALTIME) == 1
    assert fake_sensor.wait_for_command(STOP_STREAMING, timeout=1.0)
    assert fake_sensor.commands.count(STOP_STREAMING) == 1
    assert BIAS not in fake_sensor.commands


def test_main_requires_host_from_environment_and_does_not_print_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _load_hardware_tool()
    supplied_host = "sensor-host-from-environment.invalid"
    captured_configs: list[Config] = []

    def collect(config: Config, *, duration: float) -> object:
        captured_configs.append(config)
        assert duration == 2.0
        return tool.HardwareSummary(
            product_name="Product",
            force_unit="N",
            torque_unit="N-mm",
            sample_count=2,
            first_rdt_sequence=1,
            last_rdt_sequence=2,
            first_ft_sequence=1,
            last_ft_sequence=2,
            receive_rate_hz=1.0,
            delivery_rate_hz=1.0,
            received_count=2,
            delivered_count=2,
            lost_count=0,
            duplicate_count=0,
            out_of_order_count=0,
            malformed_count=0,
            reconnect_count=0,
            timeout_count=0,
        )

    monkeypatch.setattr(tool, "collect_hardware", collect)
    monkeypatch.setenv("NETFT_SENSOR_HOST", supplied_host)

    tool.main()

    assert [config.sensor_host for config in captured_configs] == [supplied_host]
    assert supplied_host not in capsys.readouterr().out


def test_main_rejects_a_missing_host(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_hardware_tool()
    monkeypatch.delenv("NETFT_SENSOR_HOST", raising=False)

    with pytest.raises(SystemExit):
        tool.main()
