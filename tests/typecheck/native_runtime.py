from operator import index

from pynetft import _native


def use_native_enum_runtime_protocol() -> tuple[int, ...]:
    force_from_int = _native.ForceUnit(_native.ForceUnit.NEWTON.value)
    force_from_member = _native.ForceUnit(_native.ForceUnit.NEWTON)
    torque = _native.TorqueUnit(_native.TorqueUnit.NEWTON_METER)
    calibration_source = _native.CalibrationSource(_native.CalibrationSource.SENSOR.value)
    recovery_policy = _native.RecoveryPolicy(_native.RecoveryPolicy.RECONNECT)
    client_state = _native.ClientState(_native.ClientState.STREAMING.value)
    fault_code = _native.FaultCode(_native.FaultCode.NONE)
    severity = _native.StatusSeverity(_native.StatusSeverity.OK.value)
    read_status = _native.ReadStatus(_native.ReadStatus.SAMPLE)
    force_members: dict[str, _native.ForceUnit] = _native.ForceUnit.__members__

    return (
        int(force_from_int),
        index(force_from_member),
        int(torque),
        index(calibration_source),
        int(recovery_policy),
        index(client_state),
        int(fault_code),
        index(severity),
        int(read_status),
        int(force_members["NEWTON"]),
    )


def use_native_sample_containers(
    sample: _native.Sample,
) -> tuple[list[int], list[float], list[float]]:
    raw_wrench: list[int] = sample.raw_wrench
    force: list[float] = sample.force
    torque: list[float] = sample.torque
    return raw_wrench, force, torque
