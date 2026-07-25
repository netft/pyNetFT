from __future__ import annotations

import importlib.util
import sys
from importlib import resources
from pathlib import Path
from types import ModuleType

from pynetft import Client, Config, ForceUnit, TorqueUnit


def _load_fake_sensor() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "integration" / "fake_sensor.py"
    specification = importlib.util.spec_from_file_location("_pynetft_artifact_fake_sensor", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_native_extension_and_type_marker_are_installed() -> None:
    import pynetft
    from pynetft import _native

    assert pynetft.__version__ == "2.0.0"
    assert _native.__version__ == pynetft.__version__
    assert resources.files("pynetft").joinpath("py.typed").is_file()


def test_installed_wheel_communicates_with_a_loopback_sensor() -> None:
    fake_sensor = _load_fake_sensor()
    with fake_sensor.FakeSensor() as sensor:
        sensor.configure(
            counts_per_force=1_000,
            counts_per_torque=100,
            force_unit="N",
            torque_unit="N-mm",
        )
        sensor.queue_record((1_000, -2_000, 3_000, 100, -200, 300))
        config = Config(
            sensor_host=sensor.host,
            rdt_port=sensor.rdt_port,
            http_port=sensor.http_port,
        )
        with Client(config) as client:
            sample = next(client.samples(timeout=1.0))

    assert sample.raw_wrench == (1_000, -2_000, 3_000, 100, -200, 300)
    assert sample.force == (1.0, -2.0, 3.0)
    assert sample.torque == (1.0, -2.0, 3.0)
    assert sample.force_unit is ForceUnit.NEWTON
    assert sample.torque_unit is TorqueUnit.NEWTON_MILLIMETER
