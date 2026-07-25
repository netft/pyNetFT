from __future__ import annotations

import warnings

import pytest

from pynetft import NetFT, Response, _native
from pynetft import _legacy as legacy_module


def _legacy_warnings(
    **kwargs: object,
) -> tuple[NetFT, list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        client = NetFT("192.168.1.1", **kwargs)
    return client, captured


def test_response_is_mutable_and_owns_a_list() -> None:
    first = Response()
    second = Response()

    first.FTData[0] = 9

    assert first.rdt_sequence == 0
    assert first.ft_sequence == 0
    assert first.status == 0
    assert first.FTData == [9, 0, 0, 0, 0, 0]
    assert second.FTData == [0, 0, 0, 0, 0, 0]


def test_legacy_constructor_warns_at_the_caller_and_discovers_by_default(
    fake_client_factory,
) -> None:
    client, captured = _legacy_warnings()

    assert len(captured) == 1
    assert captured[0].category is DeprecationWarning
    assert captured[0].filename == __file__
    assert client.count_per_force is None
    assert client.count_per_torque is None
    assert client.host == "192.168.1.1"
    assert client.port == 49152
    assert client.num_samples == 1
    assert client.is_connected is False
    assert client.AXES == ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]
    assert fake_client_factory.instance.config.calibration_override is None


def test_legacy_constructor_uses_paired_counts_as_an_n_and_n_mm_override(
    fake_client_factory,
) -> None:
    client, _ = _legacy_warnings(
        port=49153,
        count_per_force=1_000_000.0,
        count_per_torque=1_000.0,
    )
    calibration = fake_client_factory.instance.config.calibration_override

    assert client.count_per_force == 1_000_000.0
    assert client.count_per_torque == 1_000.0
    assert calibration.counts_per_force_unit == 1_000_000.0
    assert calibration.counts_per_torque_unit == 1_000.0
    assert calibration.force_unit == _native.ForceUnit.NEWTON
    assert calibration.torque_unit == _native.TorqueUnit.NEWTON_MILLIMETER


@pytest.mark.parametrize(
    ("counts",),
    [
        ({"count_per_force": 1_000_000.0},),
        ({"count_per_torque": 1_000.0},),
    ],
)
def test_partial_legacy_calibration_is_rejected(counts: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        NetFT("192.168.1.1", **counts)


def test_nondefault_num_samples_emits_a_caller_visible_deprecation(
    fake_client_factory,
) -> None:
    _, captured = _legacy_warnings(num_samples=2)

    assert [warning.category for warning in captured] == [
        DeprecationWarning,
        DeprecationWarning,
    ]
    assert all(warning.filename == __file__ for warning in captured)


def test_legacy_lifecycle_and_bias_delegate_to_modern_client(
    fake_client_factory,
) -> None:
    client, _ = _legacy_warnings()
    native = fake_client_factory.instance

    with pytest.raises(ConnectionError):
        client.bias()
    with pytest.raises(ConnectionError):
        client.get_data()
    with pytest.raises(ConnectionError):
        client.get_converted_data()

    client.connect()
    client.connect()
    client.bias()
    client.disconnect()
    client.disconnect()

    assert native.start_count == 1
    assert native.bias_count == 1
    assert native.stop_count == 1
    assert client.is_connected is False


def test_legacy_get_data_returns_a_new_response_with_raw_count_list(
    fake_client_factory, native_sample
) -> None:
    client, _ = _legacy_warnings()
    client.connect()
    fake_client_factory.instance.queue(native_sample)

    response = client.get_data()

    assert response is client.response
    assert response.rdt_sequence == 11
    assert response.ft_sequence == 12
    assert response.status == 0x10
    assert response.FTData == [1, 2, 3, 4, 5, 6]
    assert type(response.FTData) is list
    assert all(type(value) is int for value in response.FTData)
    client.disconnect()


def test_legacy_get_converted_data_returns_a_new_response_with_wrench_list(
    fake_client_factory, native_sample
) -> None:
    client, _ = _legacy_warnings()
    client.connect()
    fake_client_factory.instance.queue(native_sample)

    response = client.get_converted_data()

    assert response is client.response
    assert response.rdt_sequence == 11
    assert response.ft_sequence == 12
    assert response.status == 0x10
    assert response.FTData == [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
    assert type(response.FTData) is list
    assert all(type(value) is float for value in response.FTData)
    client.disconnect()


def test_legacy_streaming_uses_monotonic_time_and_legacy_printing(
    fake_client_factory, native_sample, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    client, _ = _legacy_warnings()
    client.connect()
    fake_client_factory.instance.queue(native_sample)
    monotonic_values = iter([0.0, 0.0, 1.0])
    sleeps: list[float] = []
    monkeypatch.setattr(legacy_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(legacy_module.time, "sleep", sleeps.append)

    client.start_streaming(duration=1.0, delay=0.25, print_data=True)

    assert sleeps == [0.25]
    assert "Status: 0x00000010" in capsys.readouterr().out
    client.disconnect()
