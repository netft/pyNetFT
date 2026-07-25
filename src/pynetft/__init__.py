from importlib.metadata import version

from ._legacy import NetFT, Response
from .client import Client
from .exceptions import (
    CallbackError,
    ConfigurationError,
    DiscoveryError,
    NetFTError,
    NotConnectedError,
    SensorFaultError,
)
from .types import (
    Calibration,
    CalibrationSource,
    ClientState,
    Config,
    FaultCode,
    ForceUnit,
    Health,
    RecoveryPolicy,
    Sample,
    SensorConfiguration,
    TorqueUnit,
)

__version__ = version("pynetft")

__all__ = [
    "__version__",
    "Client",
    "NetFT",
    "Response",
    "ForceUnit",
    "TorqueUnit",
    "CalibrationSource",
    "RecoveryPolicy",
    "ClientState",
    "FaultCode",
    "Calibration",
    "SensorConfiguration",
    "Config",
    "Sample",
    "Health",
    "NetFTError",
    "ConfigurationError",
    "DiscoveryError",
    "NotConnectedError",
    "SensorFaultError",
    "CallbackError",
]
