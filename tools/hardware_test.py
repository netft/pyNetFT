#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
from time import monotonic
from typing import NamedTuple

from pynetft import Client, ClientState, Config, FaultCode, ForceUnit, TorqueUnit

_DURATION_SECONDS = 2.0
_READ_TIMEOUT_SECONDS = 0.25


class HardwareSummary(NamedTuple):
    product_name: str
    force_unit: str
    torque_unit: str
    sample_count: int
    first_rdt_sequence: int
    last_rdt_sequence: int
    first_ft_sequence: int
    last_ft_sequence: int
    receive_rate_hz: float
    delivery_rate_hz: float
    received_count: int
    delivered_count: int
    lost_count: int
    duplicate_count: int
    out_of_order_count: int
    malformed_count: int
    reconnect_count: int
    timeout_count: int


class HardwareValidationError(RuntimeError):
    pass


def _require(condition: bool, field: str) -> None:
    if not condition:
        raise HardwareValidationError(field)


def collect_hardware(config: Config, *, duration: float = _DURATION_SECONDS) -> HardwareSummary:
    _require(math.isfinite(duration) and duration > 0.0, "duration")

    with Client(config, queue_size=4096) as client:
        try:
            first_sample = next(client.samples(timeout=_READ_TIMEOUT_SECONDS))
        except TimeoutError as error:
            raise HardwareValidationError("first_sample") from error
        samples = [first_sample]
        deadline = monotonic() + duration
        while monotonic() < deadline:
            remaining = deadline - monotonic()
            try:
                sample = next(client.samples(timeout=min(_READ_TIMEOUT_SECONDS, remaining)))
            except TimeoutError:
                continue
            samples.append(sample)

        health = client.health()

    _require(len(samples) >= 2, "sample_count")
    _require(any(sample.rdt_sequence != samples[0].rdt_sequence for sample in samples[1:]), "rdt")
    _require(any(sample.ft_sequence != samples[0].ft_sequence for sample in samples[1:]), "ft")
    _require(
        all(type(count) is int for sample in samples for count in sample.raw_wrench),
        "raw_wrench",
    )
    _require(
        all(math.isfinite(value) for sample in samples for value in sample.wrench),
        "physical_wrench",
    )

    configuration = health.sensor_configuration
    _require(configuration is not None, "sensor_configuration")
    assert configuration is not None
    calibration = configuration.calibration
    _require(
        math.isfinite(calibration.counts_per_force_unit)
        and calibration.counts_per_force_unit > 0.0,
        "counts_per_force_unit",
    )
    _require(
        math.isfinite(calibration.counts_per_torque_unit)
        and calibration.counts_per_torque_unit > 0.0,
        "counts_per_torque_unit",
    )
    _require(calibration.force_unit is not ForceUnit.UNKNOWN, "force_unit")
    _require(calibration.torque_unit is not TorqueUnit.UNKNOWN, "torque_unit")
    _require(health.state is ClientState.STREAMING, "state")
    _require(health.fault_code is FaultCode.NONE, "fault_code")
    _require(health.delivered_count >= 2, "delivered_count")

    return HardwareSummary(
        product_name=configuration.product_name,
        force_unit=calibration.force_unit.value,
        torque_unit=calibration.torque_unit.value,
        sample_count=len(samples),
        first_rdt_sequence=samples[0].rdt_sequence,
        last_rdt_sequence=samples[-1].rdt_sequence,
        first_ft_sequence=samples[0].ft_sequence,
        last_ft_sequence=samples[-1].ft_sequence,
        receive_rate_hz=health.receive_rate_hz,
        delivery_rate_hz=health.delivery_rate_hz,
        received_count=health.received_count,
        delivered_count=health.delivered_count,
        lost_count=health.lost_count,
        duplicate_count=health.duplicate_count,
        out_of_order_count=health.out_of_order_count,
        malformed_count=health.malformed_count,
        reconnect_count=health.reconnect_count,
        timeout_count=health.timeout_count,
    )


def main() -> None:
    sensor_host = os.environ.get("NETFT_SENSOR_HOST")
    if not sensor_host:
        raise SystemExit("NETFT_SENSOR_HOST is required")
    summary = collect_hardware(Config(sensor_host=sensor_host), duration=_DURATION_SECONDS)
    print(json.dumps(summary._asdict(), sort_keys=True))


if __name__ == "__main__":
    main()
