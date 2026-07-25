from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from . import _native as _native
from .types import (
    Calibration,
    CalibrationSource,
    ClientState,
    Config,
    FaultCode,
    ForceUnit,
    Health,
    Sample,
    SensorConfiguration,
    TorqueUnit,
)

_PublicEnum = TypeVar("_PublicEnum", bound=Enum)


def _to_native_enum(target: type[Any], value: Enum) -> Any:
    return getattr(target, value.name)


def _to_public_enum(target: type[_PublicEnum], value: Any) -> _PublicEnum:
    return target[value.name]


def to_native_calibration(value: Calibration) -> _native.Calibration:
    native = _native.Calibration()
    native.counts_per_force_unit = value.counts_per_force_unit
    native.counts_per_torque_unit = value.counts_per_torque_unit
    native.force_unit = _to_native_enum(_native.ForceUnit, value.force_unit)
    native.torque_unit = _to_native_enum(_native.TorqueUnit, value.torque_unit)
    return native


def to_native_config(config: Config) -> _native.Config:
    native = _native.Config()
    native.sensor_host = config.sensor_host
    native.rdt_port = config.rdt_port
    native.http_port = config.http_port
    native.receive_timeout = config.receive_timeout
    native.configuration_connect_timeout = config.configuration_connect_timeout
    native.configuration_timeout = config.configuration_timeout
    native.reconnect_initial_delay = config.reconnect_initial_delay
    native.reconnect_max_delay = config.reconnect_max_delay
    native.sample_rate_limit_hz = config.sample_rate_limit_hz
    native.deliver_samples_with_error_status = config.deliver_samples_with_error_status
    native.recovery_policy = _to_native_enum(_native.RecoveryPolicy, config.recovery_policy)
    native.calibration_override = (
        None
        if config.calibration_override is None
        else to_native_calibration(config.calibration_override)
    )
    return native


def to_sample(value: _native.Sample) -> Sample:
    raw_wrench = tuple(int(component) for component in value.raw_wrench)
    force = tuple(float(component) for component in value.force)
    torque = tuple(float(component) for component in value.torque)
    if len(raw_wrench) != 6 or len(force) != 3 or len(torque) != 3:
        raise ValueError("native sample has invalid wrench dimensions")
    return Sample(
        rdt_sequence=int(value.rdt_sequence),
        ft_sequence=int(value.ft_sequence),
        status=int(value.status),
        raw_wrench=raw_wrench,
        force=force,
        torque=torque,
        force_unit=_to_public_enum(ForceUnit, value.force_unit),
        torque_unit=_to_public_enum(TorqueUnit, value.torque_unit),
        configuration_revision=int(value.configuration_revision),
        received_at_ns=int(value.received_at_ns),
    )


def to_sensor_configuration(
    value: _native.SensorConfiguration | None,
) -> SensorConfiguration | None:
    if value is None:
        return None
    calibration = value.calibration
    return SensorConfiguration(
        product_name=value.product_name,
        calibration=Calibration(
            counts_per_force_unit=calibration.counts_per_force_unit,
            counts_per_torque_unit=calibration.counts_per_torque_unit,
            force_unit=_to_public_enum(ForceUnit, calibration.force_unit),
            torque_unit=_to_public_enum(TorqueUnit, calibration.torque_unit),
        ),
        source=_to_public_enum(CalibrationSource, value.source),
        revision=value.revision,
    )


def to_fault_code(value: _native.FaultCode) -> FaultCode:
    return _to_public_enum(FaultCode, value)


def to_health(value: _native.Health, queue_dropped_count: int) -> Health:
    return Health(
        state=_to_public_enum(ClientState, value.state),
        fault_code=to_fault_code(value.fault_code),
        sensor_host=value.sensor_host,
        rdt_port=value.rdt_port,
        sensor_configuration=to_sensor_configuration(value.sensor_configuration),
        last_rdt_sequence=value.last_rdt_sequence,
        last_ft_sequence=value.last_ft_sequence,
        last_status=value.last_status,
        receive_rate_hz=value.receive_rate_hz,
        delivery_rate_hz=value.delivery_rate_hz,
        received_count=value.received_count,
        delivered_count=value.delivered_count,
        rate_limited_count=value.rate_limited_count,
        device_error_count=value.device_error_count,
        warning_count=value.warning_count,
        lost_count=value.lost_count,
        duplicate_count=value.duplicate_count,
        out_of_order_count=value.out_of_order_count,
        malformed_count=value.malformed_count,
        reconnect_count=value.reconnect_count,
        timeout_count=value.timeout_count,
        callback_error_count=value.callback_error_count,
        ft_stall_count=value.ft_stall_count,
        ft_backward_count=value.ft_backward_count,
        ft_restart_count=value.ft_restart_count,
        calibration_change_count=value.calibration_change_count,
        last_record_age=value.last_record_age,
        last_error=value.last_error,
        last_ft_progress=value.last_ft_progress,
        python_queue_dropped_count=queue_dropped_count,
    )
