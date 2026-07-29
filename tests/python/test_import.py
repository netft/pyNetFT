from importlib.metadata import version

import pynetft
from pynetft import _native


def test_installed_version_and_native_module_agree() -> None:
    assert pynetft.__version__ == "2.1.0"
    assert version("pynetft") == pynetft.__version__
    assert _native.__version__ == pynetft.__version__


def test_public_exports_are_explicit_and_importable() -> None:
    expected = {
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
    }

    assert set(pynetft.__all__) == expected
    assert len(pynetft.__all__) == len(expected)
    assert all(hasattr(pynetft, name) for name in expected)
