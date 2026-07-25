from dataclasses import FrozenInstanceError, asdict

import pytest

from pynetft import (
    Calibration,
    CalibrationSource,
    CallbackError,
    ClientState,
    Config,
    ConfigurationError,
    DiscoveryError,
    FaultCode,
    ForceUnit,
    Health,
    NetFTError,
    NotConnectedError,
    RecoveryPolicy,
    Sample,
    SensorConfiguration,
    SensorFaultError,
    TorqueUnit,
)


def test_public_enums_have_stable_wire_values() -> None:
    assert {member.name: member.value for member in ForceUnit} == {
        "UNKNOWN": "unknown",
        "POUND_FORCE": "lbf",
        "NEWTON": "N",
        "KILO_POUND_FORCE": "klbf",
        "KILO_NEWTON": "kN",
        "KILOGRAM_FORCE": "kgf",
    }
    assert {member.name: member.value for member in TorqueUnit} == {
        "UNKNOWN": "unknown",
        "POUND_FORCE_INCH": "lbf-in",
        "POUND_FORCE_FOOT": "lbf-ft",
        "NEWTON_METER": "N-m",
        "NEWTON_MILLIMETER": "N-mm",
        "KILOGRAM_FORCE_CENTIMETER": "kgf-cm",
        "KILO_NEWTON_METER": "kN-m",
    }
    assert {member.name: member.value for member in CalibrationSource} == {
        "SENSOR": "sensor",
        "OVERRIDE": "override",
    }
    assert {member.name: member.value for member in RecoveryPolicy} == {
        "RECONNECT": "reconnect",
        "FAIL_STOP": "fail_stop",
    }
    assert {member.name: member.value for member in ClientState} == {
        "STOPPED": "stopped",
        "CONNECTING": "connecting",
        "STREAMING": "streaming",
        "BACKOFF": "backoff",
        "FAULTED": "faulted",
    }
    assert {member.name: member.value for member in FaultCode} == {
        "NONE": "none",
        "SENSOR_CONFIGURATION": "sensor_configuration",
        "TIMEOUT": "timeout",
        "SOCKET": "socket",
        "SERIOUS_STATUS": "serious_status",
        "FT_STALL": "ft_stall",
        "FT_BACKWARD": "ft_backward",
        "MALFORMED_STORM": "malformed_storm",
        "CALLBACK": "callback",
    }


def test_sample_is_immutable_and_builds_wrench() -> None:
    sample = Sample(
        rdt_sequence=1,
        ft_sequence=4,
        status=0,
        raw_wrench=(1, 2, 3, 4, 5, 6),
        force=(1.0, 2.0, 3.0),
        torque=(4.0, 5.0, 6.0),
        force_unit=ForceUnit.NEWTON,
        torque_unit=TorqueUnit.NEWTON_MILLIMETER,
        configuration_revision=1,
        received_at_ns=10,
    )
    assert sample.wrench == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    with pytest.raises(FrozenInstanceError):
        sample.status = 1  # type: ignore[misc]


def test_config_uses_ati_defaults() -> None:
    config = Config()
    assert asdict(config) == {
        "sensor_host": "192.168.1.1",
        "rdt_port": 49152,
        "http_port": 80,
        "receive_timeout": 0.1,
        "configuration_connect_timeout": 0.5,
        "configuration_timeout": 1.0,
        "reconnect_initial_delay": 0.25,
        "reconnect_max_delay": 5.0,
        "sample_rate_limit_hz": 0.0,
        "deliver_samples_with_error_status": False,
        "recovery_policy": RecoveryPolicy.RECONNECT,
        "calibration_override": None,
    }


def test_value_objects_are_immutable() -> None:
    calibration = Calibration(
        counts_per_force_unit=1_000_000,
        counts_per_torque_unit=1_000,
        force_unit=ForceUnit.NEWTON,
        torque_unit=TorqueUnit.NEWTON_MILLIMETER,
    )
    configuration = SensorConfiguration(
        product_name="ATI Mini45",
        calibration=calibration,
        source=CalibrationSource.SENSOR,
        revision=1,
    )
    values = [
        (calibration, "counts_per_force_unit"),
        (configuration, "revision"),
        (Config(), "rdt_port"),
        (Health.empty("127.0.0.1", 49152), "received_count"),
    ]

    for value, attribute in values:
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute, 1)


def test_health_empty_uses_neutral_counters_and_requested_endpoint() -> None:
    assert asdict(Health.empty("sensor.example", 50000)) == {
        "state": ClientState.STOPPED,
        "fault_code": FaultCode.NONE,
        "sensor_host": "sensor.example",
        "rdt_port": 50000,
        "sensor_configuration": None,
        "last_rdt_sequence": None,
        "last_ft_sequence": None,
        "last_status": 0,
        "receive_rate_hz": 0.0,
        "delivery_rate_hz": 0.0,
        "received_count": 0,
        "delivered_count": 0,
        "rate_limited_count": 0,
        "device_error_count": 0,
        "warning_count": 0,
        "lost_count": 0,
        "duplicate_count": 0,
        "out_of_order_count": 0,
        "malformed_count": 0,
        "reconnect_count": 0,
        "timeout_count": 0,
        "callback_error_count": 0,
        "ft_stall_count": 0,
        "ft_backward_count": 0,
        "ft_restart_count": 0,
        "calibration_change_count": 0,
        "last_record_age": None,
        "last_error": "",
        "last_ft_progress": "unknown",
        "python_queue_dropped_count": 0,
    }


def test_sensor_fault_is_structured() -> None:
    health = Health.empty("192.168.1.1", 49152)
    error = SensorFaultError(FaultCode.TIMEOUT, health)
    assert error.fault_code is FaultCode.TIMEOUT
    assert error.health is health


def test_exception_classes_preserve_builtin_catch_points() -> None:
    assert issubclass(ConfigurationError, NetFTError)
    assert issubclass(ConfigurationError, ValueError)
    assert issubclass(DiscoveryError, NetFTError)
    assert issubclass(DiscoveryError, ConnectionError)
    assert issubclass(NotConnectedError, NetFTError)
    assert issubclass(NotConnectedError, ConnectionError)
    assert issubclass(SensorFaultError, NetFTError)
    assert issubclass(CallbackError, NetFTError)
