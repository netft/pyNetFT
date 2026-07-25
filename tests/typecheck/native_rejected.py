from pynetft import _native


def reject_native_mutation_and_iteration(
    sample: _native.Sample,
    health: _native.Health,
    result: _native.ReadResult,
) -> None:
    sample.rdt_sequence = 1
    health.received_count = 1
    result.status = _native.ReadStatus.CLOSED
    for _member in _native.ForceUnit:
        pass
