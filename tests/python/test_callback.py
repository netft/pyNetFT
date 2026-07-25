from __future__ import annotations

import threading

import pytest

from pynetft import (
    CallbackError,
    Client,
    ClientState,
    Config,
    ConfigurationError,
    DiscoveryError,
    FaultCode,
    Sample,
    SensorFaultError,
    _native,
)


def test_callback_runs_on_python_dispatcher(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[Sample] = []
    callback_threads: list[threading.Thread] = []
    read_threads: list[threading.Thread] = []
    delivered = threading.Event()

    def capture(sample: Sample) -> None:
        received.append(sample)
        callback_threads.append(threading.current_thread())
        delivered.set()

    client = Client(Config(), callback=capture)
    native = fake_client_factory.instance
    native_read = native.read

    def record_read_thread(timeout: float | None):
        read_threads.append(threading.current_thread())
        return native_read(timeout)

    monkeypatch.setattr(native, "read", record_read_thread)
    with client:
        native.queue(native_sample)
        assert delivered.wait(1.0)

    assert [sample.raw_wrench for sample in received] == [(1, 2, 3, 4, 5, 6)]
    assert len(callback_threads) == 1
    assert callback_threads[0] is not threading.current_thread()
    assert callback_threads[0] in read_threads
    assert not callback_threads[0].daemon
    assert not callback_threads[0].is_alive()


def test_start_argument_enables_callback_delivery(fake_client_factory, native_sample) -> None:
    received: list[Sample] = []
    delivered = threading.Event()

    def capture(sample: Sample) -> None:
        received.append(sample)
        delivered.set()

    client = Client(Config())
    try:
        client.start(capture)
        fake_client_factory.instance.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        client.stop()

    assert [sample.rdt_sequence for sample in received] == [11]


def test_callback_error_preserves_cause_without_uncaught_thread_noise(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("sentinel")
    uncaught: list[threading.ExceptHookArgs] = []

    def fail(_: Sample) -> None:
        raise original

    monkeypatch.setattr(threading, "excepthook", uncaught.append)
    client = Client(Config(), callback=fail)
    try:
        client.start()
        fake_client_factory.instance.queue(native_sample)

        with pytest.raises(CallbackError) as captured:
            client.wait(timeout=1.0)
        with pytest.raises(CallbackError) as raised_again:
            client.raise_if_failed()
    finally:
        client.stop()

    assert captured.value.__cause__ is original
    assert raised_again.value.__cause__ is original
    assert fake_client_factory.instance.stopped
    assert uncaught == []


def test_callback_catches_base_exception(fake_client_factory, native_sample) -> None:
    original = KeyboardInterrupt()

    def fail(_: Sample) -> None:
        raise original

    client = Client(Config(), callback=fail)
    try:
        client.start()
        fake_client_factory.instance.queue(native_sample)

        with pytest.raises(CallbackError) as captured:
            client.wait(timeout=1.0)
    finally:
        client.stop()

    assert captured.value.__cause__ is original


def test_dispatcher_failure_is_callback_error(
    fake_client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("dispatcher")
    client = Client(Config(), callback=lambda _: None)

    def fail_read(_: float | None):
        raise original

    monkeypatch.setattr(fake_client_factory.instance, "read", fail_read)
    try:
        client.start()

        with pytest.raises(CallbackError) as captured:
            client.wait(timeout=1.0)
    finally:
        client.stop()

    assert captured.value.__cause__ is original


def test_native_dispatch_failure_preserves_translation(
    fake_client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _native.ValidationError("native")
    client = Client(Config(), callback=lambda _: None)

    def fail_read(_: float | None):
        raise original

    monkeypatch.setattr(fake_client_factory.instance, "read", fail_read)
    try:
        client.start()

        with pytest.raises(CallbackError) as captured:
            client.wait(timeout=1.0)
    finally:
        client.stop()

    assert isinstance(captured.value.__cause__, ConfigurationError)
    assert captured.value.__cause__.__cause__ is original


def test_wait_timeout_does_not_stop_callback_run(fake_client_factory) -> None:
    client = Client(Config(), callback=lambda _: None)
    try:
        client.start()

        with pytest.raises(TimeoutError):
            client.wait(timeout=0.001)

        assert fake_client_factory.instance.started
        assert not fake_client_factory.instance.stopped
    finally:
        client.stop()


def test_callback_and_iterator_modes_are_mutually_exclusive(
    fake_client_factory,
) -> None:
    client = Client(Config(), callback=lambda _: None)
    try:
        client.start()

        with pytest.raises(RuntimeError):
            client.samples()
    finally:
        client.stop()


def test_running_callback_rejects_a_different_callback(
    fake_client_factory,
) -> None:
    def first(_: Sample) -> None:
        pass

    def second(_: Sample) -> None:
        pass

    client = Client(Config())
    try:
        client.start(first)
        client.start(first)

        with pytest.raises(RuntimeError):
            client.start(second)

        assert fake_client_factory.instance.start_count == 1
    finally:
        client.stop()


def test_stop_waits_for_active_callback_to_return(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_entered = threading.Event()
    release_callback = threading.Event()
    native_stop_called = threading.Event()
    stop_returned = threading.Event()

    def block(_: Sample) -> None:
        callback_entered.set()
        release_callback.wait()

    client = Client(Config(), callback=block)
    native = fake_client_factory.instance
    native_stop = native.stop

    def observe_stop() -> None:
        native_stop()
        native_stop_called.set()

    def stop_client() -> None:
        client.stop()
        stop_returned.set()

    stopper = threading.Thread(target=stop_client)
    monkeypatch.setattr(native, "stop", observe_stop)
    try:
        client.start()
        native.queue(native_sample)
        assert callback_entered.wait(1.0)

        stopper.start()
        assert native_stop_called.wait(1.0)
        assert not stop_returned.is_set()
    finally:
        release_callback.set()
        client.stop()
        if stopper.ident is not None:
            stopper.join(1.0)

    assert not stopper.is_alive()
    assert stop_returned.is_set()


def test_callback_join_snapshots_dispatcher_reference() -> None:
    from pynetft import client as client_module

    class JoinableThread:
        def __init__(self) -> None:
            self.join_count = 0

        def join(self) -> None:
            self.join_count += 1

    class ConcurrentlyClearedRun:
        def __init__(self, thread: JoinableThread) -> None:
            self._thread = thread
            self.access_count = 0

        @property
        def thread(self) -> JoinableThread | None:
            self.access_count += 1
            if self.access_count >= 3:
                return None
            return self._thread

    dispatcher = JoinableThread()
    callback_run = ConcurrentlyClearedRun(dispatcher)

    client_module.Client._join_callback_run(callback_run)

    assert callback_run.access_count == 1
    assert dispatcher.join_count == 1


def test_callback_can_stop_its_own_run_without_self_join(
    fake_client_factory, native_sample
) -> None:
    stop_returned = threading.Event()
    client: Client

    def stop_from_callback(_: Sample) -> None:
        client.stop()
        stop_returned.set()

    client = Client(Config(), callback=stop_from_callback)
    try:
        client.start()
        fake_client_factory.instance.queue(native_sample)

        assert stop_returned.wait(1.0)
        client.wait(timeout=1.0)
    finally:
        client.stop()

    assert fake_client_factory.instance.stopped


def test_callback_dispatcher_cannot_start_after_self_stop(
    fake_client_factory, native_sample
) -> None:
    outcomes: list[str] = []
    attempted = threading.Event()
    client: Client

    def stop_then_try_to_start(_: Sample) -> None:
        client.stop()
        try:
            client.start(lambda _: None)
        except RuntimeError:
            outcomes.append("rejected")
        else:
            outcomes.append("started")
        finally:
            attempted.set()

    client = Client(Config(), callback=stop_then_try_to_start)
    try:
        client.start()
        fake_client_factory.instance.queue(native_sample)
        assert attempted.wait(1.0)
    finally:
        client.stop()

    assert outcomes == ["rejected"]
    assert fake_client_factory.instance.start_count == 1


def test_external_start_waits_for_self_stopped_dispatcher(
    fake_client_factory, native_sample
) -> None:
    self_stopped = threading.Event()
    release_old_callback = threading.Event()
    restart_returned = threading.Event()
    new_delivered = threading.Event()
    old_dispatchers: list[threading.Thread] = []
    restart_errors: list[BaseException] = []
    client: Client

    def stop_then_block(_: Sample) -> None:
        old_dispatchers.append(threading.current_thread())
        client.stop()
        self_stopped.set()
        release_old_callback.wait()

    def restart() -> None:
        try:
            client.start(lambda _: new_delivered.set())
        except BaseException as error:
            restart_errors.append(error)
        finally:
            restart_returned.set()

    client = Client(Config(), callback=stop_then_block)
    restarter = threading.Thread(target=restart)
    try:
        client.start()
        fake_client_factory.instance.queue(native_sample)
        assert self_stopped.wait(1.0)

        restarter.start()
        assert not restart_returned.wait(0.1)
        assert fake_client_factory.instance.start_count == 1

        release_old_callback.set()
        restarter.join(1.0)
        assert not restarter.is_alive()
        assert restart_returned.is_set()
        assert restart_errors == []
        assert not old_dispatchers[0].is_alive()

        fake_client_factory.instance.queue(native_sample)
        assert new_delivered.wait(1.0)
    finally:
        release_old_callback.set()
        if restarter.ident is not None:
            restarter.join(1.0)
        client.stop()


def test_stale_dispatcher_terminates_before_external_restart(
    fake_client_factory, native_sample
) -> None:
    old_deliveries: list[Sample] = []
    new_deliveries: list[Sample] = []
    restarted = threading.Event()
    new_delivered = threading.Event()

    def capture_new(sample: Sample) -> None:
        new_deliveries.append(sample)
        new_delivered.set()

    client = Client(Config(), callback=old_deliveries.append)
    native = fake_client_factory.instance
    native.pause_next_read_after_wake()
    stopper = threading.Thread(target=client.stop)

    def restart() -> None:
        client.start(capture_new)
        restarted.set()

    restarter = threading.Thread(target=restart)
    try:
        client.start()
        assert native.wait_until_read()

        stopper.start()
        assert native.wait_until_read_paused()
        restarter.start()
        assert not restarted.is_set()

        native.release_paused_read()
        stopper.join(1.0)
        restarter.join(1.0)
        assert not stopper.is_alive()
        assert not restarter.is_alive()
        assert restarted.is_set()

        native.queue(native_sample)
        assert new_delivered.wait(1.0)
    finally:
        native.release_paused_read()
        if stopper.ident is not None:
            stopper.join(1.0)
        if restarter.ident is not None:
            restarter.join(1.0)
        client.stop()
        if stopper.ident is not None:
            stopper.join(1.0)
        if restarter.ident is not None:
            restarter.join(1.0)

    assert not stopper.is_alive()
    assert not restarter.is_alive()
    assert old_deliveries == []
    assert [sample.rdt_sequence for sample in new_deliveries] == [11]


def test_callback_fault_snapshot_and_stop_are_run_atomic(
    fake_client_factory, native_health, native_sample
) -> None:
    delivered = threading.Event()
    stop_attempted = threading.Event()
    old_stop_finished = threading.Event()
    allow_restart = threading.Event()
    restarted = threading.Event()

    client = Client(Config(), callback=lambda _: delivered.set())
    native = fake_client_factory.instance

    def stop_then_restart() -> None:
        stop_attempted.set()
        client.stop()
        old_stop_finished.set()
        allow_restart.wait()
        native.faulted_value = False
        native.fault_code_value = _native.FaultCode.NONE
        client.start()
        restarted.set()

    restarter = threading.Thread(target=stop_then_restart)
    try:
        client.start()
        native.health_value = native_health
        native.faulted_value = True
        native.fault_code_value = _native.FaultCode.TIMEOUT
        native.dropped_value = 17
        native.pause_fault_inspection()
        native.stop()
        assert native.wait_until_fault_inspection()

        restarter.start()
        assert stop_attempted.wait(1.0)
        assert not old_stop_finished.is_set()

        native.release_fault_inspection()
        assert old_stop_finished.wait(1.0)
        with pytest.raises(SensorFaultError) as captured:
            client.wait(timeout=1.0)

        assert captured.value.fault_code is FaultCode.TIMEOUT
        assert captured.value.health.state is ClientState.FAULTED
        assert captured.value.health.python_queue_dropped_count == 17

        allow_restart.set()
        assert restarted.wait(1.0)
        native.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        native.release_fault_inspection()
        allow_restart.set()
        if restarter.ident is not None:
            restarter.join(1.0)
        client.stop()
        if restarter.ident is not None:
            restarter.join(1.0)

    assert not restarter.is_alive()


def test_dispatcher_start_failure_has_no_native_side_effect_and_can_retry(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("dispatcher start")
    delivered = threading.Event()
    thread_start = threading.Thread.start

    def reject_dispatcher_start(thread: threading.Thread) -> None:
        if thread.name.startswith("pynetft-callback-"):
            raise original
        thread_start(thread)

    monkeypatch.setattr(threading.Thread, "start", reject_dispatcher_start)
    client = Client(Config(), callback=lambda _: delivered.set())
    native = fake_client_factory.instance

    with pytest.raises(RuntimeError) as captured:
        client.start()

    assert captured.value is original
    assert native.start_count == 0
    assert native.stop_count == 0

    monkeypatch.setattr(threading.Thread, "start", thread_start)
    try:
        client.start()
        native.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        client.stop()


def test_callback_run_construction_failure_has_no_native_side_effect(
    fake_client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    original = RuntimeError("callback run construction")
    callback_run_type = client_module._CallbackRun
    client = Client(Config(), callback=lambda _: None)
    native = fake_client_factory.instance

    def reject_callback_run(*_: object, **__: object):
        raise original

    monkeypatch.setattr(client_module, "_CallbackRun", reject_callback_run)
    with pytest.raises(RuntimeError) as captured:
        client.start()

    assert captured.value is original
    assert native.start_count == 0
    assert native.stop_count == 0
    monkeypatch.setattr(client_module, "_CallbackRun", callback_run_type)


def test_dispatcher_construction_failure_has_no_native_side_effect(
    fake_client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    original = RuntimeError("dispatcher construction")
    thread_type = client_module.Thread
    client = Client(Config(), callback=lambda _: None)
    native = fake_client_factory.instance

    def reject_dispatcher(*_: object, **__: object):
        raise original

    monkeypatch.setattr(client_module, "Thread", reject_dispatcher)
    with pytest.raises(RuntimeError) as captured:
        client.start()

    assert captured.value is original
    assert native.start_count == 0
    assert native.stop_count == 0
    monkeypatch.setattr(client_module, "Thread", thread_type)


def test_dispatcher_waits_for_native_start_commit_before_reading(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    dispatcher_started = threading.Event()
    native_start_entered = threading.Event()
    release_native_start = threading.Event()
    start_returned = threading.Event()
    delivered = threading.Event()
    errors: list[BaseException] = []
    callback_runs = []
    original_thread_type = client_module.Thread
    client = Client(Config(), callback=lambda _: delivered.set())
    native = fake_client_factory.instance
    native_start = native.start

    class ObservedThread(original_thread_type):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            callback_runs.append(kwargs["args"][1]())

        def start(self) -> None:
            super().start()
            dispatcher_started.set()

    def block_native_start() -> None:
        native_start_entered.set()
        release_native_start.wait()
        native_start()

    def start_client() -> None:
        try:
            client.start()
        except BaseException as error:
            errors.append(error)
        finally:
            start_returned.set()

    starter = threading.Thread(target=start_client)
    monkeypatch.setattr(client_module, "Thread", ObservedThread)
    monkeypatch.setattr(native, "start", block_native_start)
    try:
        starter.start()
        assert native_start_entered.wait(1.0)
        assert dispatcher_started.is_set()
        assert native.read_count == 0
        assert not start_returned.is_set()

        release_native_start.set()
        starter.join(1.0)
        assert not starter.is_alive()
        assert errors == []

        native.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        release_native_start.set()
        if starter.ident is not None:
            starter.join(1.0)
        for callback_run in callback_runs:
            if callback_run is not None:
                callback_run.activation.cancel()
        client.stop()


def test_native_start_failure_cancels_and_joins_prestarted_dispatcher(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    original = _native.DiscoveryError("missing sensor")
    original_thread_type = client_module.Thread
    dispatchers: list[threading.Thread] = []
    callback_runs = []
    delivered = threading.Event()
    client = Client(Config(), callback=lambda _: delivered.set())
    native = fake_client_factory.instance
    native.start_error = original

    class CapturedThread(original_thread_type):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            callback_runs.append(kwargs["args"][1]())

        def start(self) -> None:
            dispatchers.append(self)
            super().start()

    monkeypatch.setattr(client_module, "Thread", CapturedThread)
    try:
        with pytest.raises(DiscoveryError) as captured:
            client.start()

        assert captured.value.__cause__ is original
        assert len(dispatchers) == 1
        assert not dispatchers[0].is_alive()
        assert native.read_count == 0
    finally:
        native.start_error = None
        for callback_run in callback_runs:
            if callback_run is not None:
                callback_run.activation.cancel()
        for dispatcher in dispatchers:
            dispatcher.join(1.0)
        client.stop()

    monkeypatch.setattr(client_module, "Thread", original_thread_type)
    try:
        client.start()
        native.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        client.stop()


def test_thread_start_base_exception_cancels_without_native_access(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    interruption = KeyboardInterrupt()
    original_thread_type = client_module.Thread
    dispatchers: list[threading.Thread] = []
    callback_runs = []
    delivered = threading.Event()
    client = Client(Config(), callback=lambda _: delivered.set())
    native = fake_client_factory.instance

    class InterruptedStartThread(original_thread_type):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            callback_runs.append(kwargs["args"][1]())

        def start(self) -> None:
            dispatchers.append(self)
            super().start()
            raise interruption

    monkeypatch.setattr(client_module, "Thread", InterruptedStartThread)
    try:
        with pytest.raises(KeyboardInterrupt) as captured:
            client.start()

        assert captured.value is interruption
        assert native.start_count == 0
        assert native.read_count == 0
        assert len(dispatchers) == 1
        dispatchers[0].join(1.0)
        assert not dispatchers[0].is_alive()
    finally:
        for callback_run in callback_runs:
            if callback_run is not None:
                callback_run.activation.cancel()
        for dispatcher in dispatchers:
            dispatcher.join(1.0)
        client.stop()

    monkeypatch.setattr(client_module, "Thread", original_thread_type)
    try:
        client.start()
        native.queue(native_sample)
        assert delivered.wait(1.0)
    finally:
        client.stop()


def test_failed_external_start_preserves_old_failure_until_success(
    fake_client_factory,
    native_sample,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pynetft import client as client_module

    callback_error = RuntimeError("old callback")
    start_error = RuntimeError("new dispatcher construction")
    original_thread_type = client_module.Thread
    new_delivered = threading.Event()

    def fail(_: Sample) -> None:
        raise callback_error

    client = Client(Config(), callback=fail)
    client.start()
    fake_client_factory.instance.queue(native_sample)
    with pytest.raises(CallbackError):
        client.wait(timeout=1.0)

    def reject_dispatcher(*_: object, **__: object):
        raise start_error

    monkeypatch.setattr(client_module, "Thread", reject_dispatcher)
    with pytest.raises(RuntimeError) as captured_start:
        client.start(lambda _: new_delivered.set())

    assert captured_start.value is start_error
    with pytest.raises(CallbackError) as captured_old:
        client.raise_if_failed()
    with pytest.raises(CallbackError) as waited_old:
        client.wait(timeout=1.0)
    assert captured_old.value.__cause__ is callback_error
    assert waited_old.value.__cause__ is callback_error

    monkeypatch.setattr(client_module, "Thread", original_thread_type)
    native = fake_client_factory.instance
    native_error = _native.DiscoveryError("new native start")
    native.start_error = native_error
    with pytest.raises(DiscoveryError) as captured_native:
        client.start(lambda _: new_delivered.set())
    assert captured_native.value.__cause__ is native_error
    with pytest.raises(CallbackError) as preserved_again:
        client.raise_if_failed()
    assert preserved_again.value.__cause__ is callback_error

    native.start_error = None
    try:
        client.start(lambda _: new_delivered.set())
        native.queue(native_sample)
        assert new_delivered.wait(1.0)
        client.raise_if_failed()
    finally:
        client.stop()
