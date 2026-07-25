from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field

from .client import Client
from .types import Calibration, Config, ForceUnit, Sample, TorqueUnit


@dataclass
class Response:
    rdt_sequence: int = 0
    ft_sequence: int = 0
    status: int = 0
    FTData: list[int | float] = field(default_factory=lambda: [0] * 6)


class NetFT:
    """Deprecated adapter for the pyNetFT 1.x API."""

    def __init__(
        self,
        host: str,
        port: int = 49152,
        num_samples: int = 1,
        count_per_force: float | None = None,
        count_per_torque: float | None = None,
    ) -> None:
        if (count_per_force is None) != (count_per_torque is None):
            raise ValueError("count_per_force and count_per_torque must be provided together")

        warnings.warn(
            "NetFT is deprecated; use Client instead",
            DeprecationWarning,
            stacklevel=2,
        )
        if num_samples != 1:
            warnings.warn(
                "num_samples is ignored because Client uses a continuous stream",
                DeprecationWarning,
                stacklevel=2,
            )

        calibration_override = None
        if count_per_force is not None and count_per_torque is not None:
            calibration_override = Calibration(
                counts_per_force_unit=count_per_force,
                counts_per_torque_unit=count_per_torque,
                force_unit=ForceUnit.NEWTON,
                torque_unit=TorqueUnit.NEWTON_MILLIMETER,
            )

        self.host = host
        self.port = port
        self.num_samples = num_samples
        self.count_per_force = count_per_force
        self.count_per_torque = count_per_torque
        self.AXES = ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]
        self.response = Response()
        self.is_connected = False
        self.modern_client = Client(
            Config(
                sensor_host=host,
                rdt_port=port,
                calibration_override=calibration_override,
            )
        )

    def connect(self) -> None:
        self.modern_client.start()
        self.is_connected = True

    def disconnect(self) -> None:
        if not self.is_connected:
            return
        self.modern_client.stop()
        self.is_connected = False

    def bias(self) -> None:
        self._require_connection()
        self.modern_client.bias()

    def get_data(self) -> Response:
        return self._response_from_sample(self._next_sample(), raw=True)

    def get_converted_data(self) -> Response:
        return self._response_from_sample(self._next_sample(), raw=False)

    def start_streaming(
        self, duration: float = 10, delay: float = 0.1, print_data: bool = True
    ) -> None:
        started_at = time.monotonic()
        while time.monotonic() - started_at < duration:
            response = self.get_converted_data()
            if print_data:
                self._print_data(response)
            time.sleep(delay)
        print("Data streaming stopped")

    def _next_sample(self) -> Sample:
        self._require_connection()
        return next(self.modern_client.samples())

    def _require_connection(self) -> None:
        if not self.is_connected:
            raise ConnectionError("Not connected; call connect() first")

    def _response_from_sample(self, sample: Sample, *, raw: bool) -> Response:
        values: list[int | float] = []
        values.extend(sample.raw_wrench if raw else sample.wrench)
        response = Response(
            rdt_sequence=sample.rdt_sequence,
            ft_sequence=sample.ft_sequence,
            status=sample.status,
            FTData=values,
        )
        self.response = response
        return response

    def _print_data(self, response: Response) -> None:
        print(f"Status: 0x{response.status:08x}")
        for axis, value in zip(self.AXES, response.FTData, strict=True):
            print(f"{axis}: {value}")
