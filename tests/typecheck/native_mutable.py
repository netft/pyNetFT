from pynetft import _native


def assign_mutable_native_fields(
    calibration: _native.Calibration,
    configuration: _native.SensorConfiguration,
    config: _native.Config,
) -> tuple[str, int]:
    calibration.counts_per_force_unit = 1.0
    calibration.counts_per_torque_unit = 2.0
    calibration.force_unit = _native.ForceUnit.NEWTON
    calibration.torque_unit = _native.TorqueUnit.NEWTON_METER
    configuration.product_name = "sensor"
    configuration.calibration = calibration
    configuration.source = _native.CalibrationSource.OVERRIDE
    configuration.revision = 2
    config.sensor_host = "sensor"
    config.rdt_port = 49152
    config.http_port = 80
    config.receive_timeout = 0.1
    config.configuration_connect_timeout = 0.5
    config.configuration_timeout = 1.0
    config.reconnect_initial_delay = 0.25
    config.reconnect_max_delay = 5.0
    config.sample_rate_limit_hz = 100.0
    config.deliver_samples_with_error_status = True
    config.recovery_policy = _native.RecoveryPolicy.FAIL_STOP
    config.calibration_override = calibration
    return _native.ForceUnit.NEWTON.name, _native.ReadStatus.SAMPLE.value
