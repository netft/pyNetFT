from dataclasses import dataclass
from enum import Enum


class ForceUnit(str, Enum):
    UNKNOWN = "unknown"
    POUND_FORCE = "lbf"
    NEWTON = "N"
    KILO_POUND_FORCE = "klbf"
    KILO_NEWTON = "kN"
    KILOGRAM_FORCE = "kgf"


class TorqueUnit(str, Enum):
    UNKNOWN = "unknown"
    POUND_FORCE_INCH = "lbf-in"
    POUND_FORCE_FOOT = "lbf-ft"
    NEWTON_METER = "N-m"
    NEWTON_MILLIMETER = "N-mm"
    KILOGRAM_FORCE_CENTIMETER = "kgf-cm"
    KILO_NEWTON_METER = "kN-m"


class CalibrationSource(str, Enum):
    SENSOR = "sensor"
    OVERRIDE = "override"


class RecoveryPolicy(str, Enum):
    RECONNECT = "reconnect"
    FAIL_STOP = "fail_stop"


class ClientState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    BACKOFF = "backoff"
    FAULTED = "faulted"


class FaultCode(str, Enum):
    NONE = "none"
    SENSOR_CONFIGURATION = "sensor_configuration"
    TIMEOUT = "timeout"
    SOCKET = "socket"
    SERIOUS_STATUS = "serious_status"
    FT_STALL = "ft_stall"
    FT_BACKWARD = "ft_backward"
    MALFORMED_STORM = "malformed_storm"
    CALLBACK = "callback"


@dataclass(frozen=True, slots=True)
class Calibration:
    counts_per_force_unit: float
    counts_per_torque_unit: float
    force_unit: ForceUnit
    torque_unit: TorqueUnit


@dataclass(frozen=True, slots=True)
class SensorConfiguration:
    product_name: str
    calibration: Calibration
    source: CalibrationSource
    revision: int


@dataclass(frozen=True, slots=True)
class Config:
    sensor_host: str = "192.168.1.1"
    rdt_port: int = 49152
    http_port: int = 80
    receive_timeout: float = 0.1
    configuration_connect_timeout: float = 0.5
    configuration_timeout: float = 1.0
    reconnect_initial_delay: float = 0.25
    reconnect_max_delay: float = 5.0
    sample_rate_limit_hz: float = 0.0
    deliver_samples_with_error_status: bool = False
    recovery_policy: RecoveryPolicy = RecoveryPolicy.RECONNECT
    calibration_override: Calibration | None = None


@dataclass(frozen=True, slots=True)
class Sample:
    rdt_sequence: int
    ft_sequence: int
    status: int
    raw_wrench: tuple[int, int, int, int, int, int]
    force: tuple[float, float, float]
    torque: tuple[float, float, float]
    force_unit: ForceUnit
    torque_unit: TorqueUnit
    configuration_revision: int
    received_at_ns: int

    @property
    def wrench(self) -> tuple[float, float, float, float, float, float]:
        return (*self.force, *self.torque)


@dataclass(frozen=True, slots=True)
class Health:
    state: ClientState
    fault_code: FaultCode
    sensor_host: str
    rdt_port: int
    sensor_configuration: SensorConfiguration | None
    last_rdt_sequence: int | None
    last_ft_sequence: int | None
    last_status: int
    receive_rate_hz: float
    delivery_rate_hz: float
    received_count: int
    delivered_count: int
    rate_limited_count: int
    device_error_count: int
    warning_count: int
    lost_count: int
    duplicate_count: int
    out_of_order_count: int
    malformed_count: int
    reconnect_count: int
    timeout_count: int
    callback_error_count: int
    ft_stall_count: int
    ft_backward_count: int
    ft_restart_count: int
    calibration_change_count: int
    last_record_age: float | None
    last_error: str
    last_ft_progress: str
    python_queue_dropped_count: int

    @classmethod
    def empty(cls, sensor_host: str, rdt_port: int) -> "Health":
        return cls(
            state=ClientState.STOPPED,
            fault_code=FaultCode.NONE,
            sensor_host=sensor_host,
            rdt_port=rdt_port,
            sensor_configuration=None,
            last_rdt_sequence=None,
            last_ft_sequence=None,
            last_status=0,
            receive_rate_hz=0.0,
            delivery_rate_hz=0.0,
            received_count=0,
            delivered_count=0,
            rate_limited_count=0,
            device_error_count=0,
            warning_count=0,
            lost_count=0,
            duplicate_count=0,
            out_of_order_count=0,
            malformed_count=0,
            reconnect_count=0,
            timeout_count=0,
            callback_error_count=0,
            ft_stall_count=0,
            ft_backward_count=0,
            ft_restart_count=0,
            calibration_change_count=0,
            last_record_age=None,
            last_error="",
            last_ft_progress="unknown",
            python_queue_dropped_count=0,
        )
