from .types import FaultCode, Health


class NetFTError(Exception):
    pass


class ConfigurationError(NetFTError, ValueError):
    pass


class DiscoveryError(NetFTError, ConnectionError):
    pass


class NotConnectedError(NetFTError, ConnectionError):
    pass


class SensorFaultError(NetFTError):
    def __init__(self, fault_code: FaultCode, health: Health) -> None:
        self.fault_code = fault_code
        self.health = health
        super().__init__(fault_code.value)


class CallbackError(NetFTError):
    pass
