from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Event, Lock, Thread, current_thread
from types import TracebackType
from typing import Literal
from weakref import ReferenceType, ref

from . import _native as _native
from ._conversion import to_fault_code, to_health, to_native_config, to_sample
from .exceptions import (
    CallbackError,
    ConfigurationError,
    DiscoveryError,
    NotConnectedError,
    SensorFaultError,
)
from .types import Config, Health, Sample

_Mode = Literal["iterator", "callback"]


class _CallbackActivation:
    def __init__(self) -> None:
        self._ready = Event()
        self._lock = Lock()
        self._active = False

    def activate(self) -> None:
        with self._lock:
            self._active = True
            self._ready.set()

    def cancel(self) -> None:
        with self._lock:
            self._active = False
            self._ready.set()

    def wait(self) -> bool:
        self._ready.wait()
        with self._lock:
            return self._active


@dataclass
class _CallbackRun:
    token: int
    callback: Callable[[Sample], None] | None
    activation: _CallbackActivation = field(default_factory=_CallbackActivation)
    completed: Event = field(default_factory=Event)
    thread: Thread | None = None
    callback_error: BaseException | None = None
    failure: SensorFaultError | None = None


@dataclass(frozen=True)
class _CallbackStartFailure:
    error: BaseException
    traceback: TracebackType | None
    callback_run: _CallbackRun | None
    join_dispatcher: bool


class Client:
    def __init__(
        self,
        config: Config,
        *,
        queue_size: int = 1,
        callback: Callable[[Sample], None] | None = None,
    ) -> None:
        self._lock = Lock()
        self._running = False
        self._mode: _Mode | None = None
        self._run_token = 0
        self._constructor_callback = callback
        self._callback_run: _CallbackRun | None = None
        try:
            native_config = to_native_config(config)
            self._native = _native.NativeClient(native_config, queue_size)
        except _native.ValidationError as error:
            raise ConfigurationError(str(error)) from error

    def __enter__(self) -> Client:
        self.start(self._constructor_callback)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self, callback: Callable[[Sample], None] | None = None) -> None:
        selected_callback = self._constructor_callback if callback is None else callback
        requested_mode: _Mode = "callback" if selected_callback is not None else "iterator"
        while True:
            callback_run_to_join: _CallbackRun | None = None
            start_failure: _CallbackStartFailure | None = None
            with self._lock:
                caller = current_thread()
                current_callback_run = self._callback_run
                if current_callback_run is not None and current_callback_run.thread is caller:
                    raise RuntimeError("a callback dispatcher cannot start its client")
                if self._running:
                    if self._mode != requested_mode:
                        raise RuntimeError("cannot change delivery mode while running")
                    if (
                        requested_mode == "callback"
                        and self._callback_run is not None
                        and self._callback_run.callback is not selected_callback
                    ):
                        raise RuntimeError("cannot change callback while running")
                    return
                if current_callback_run is not None and current_callback_run.thread is not None:
                    callback_run_to_join = current_callback_run
                if callback_run_to_join is None:
                    start_failure = self._start_locked(requested_mode, selected_callback)
            if callback_run_to_join is not None:
                joined_thread = callback_run_to_join.thread
                self._join_callback_run(callback_run_to_join)
                with self._lock:
                    if (
                        self._callback_run is callback_run_to_join
                        and callback_run_to_join.thread is joined_thread
                    ):
                        callback_run_to_join.thread = None
                continue
            if start_failure is not None:
                self._finish_failed_callback_start(start_failure)
            return

    def stop(self) -> None:
        with self._lock:
            caller = current_thread()
            callback_run = self._callback_run
            self._stop_locked()
            callback_run_to_join = (
                callback_run
                if callback_run is not None
                and callback_run.thread is not None
                and callback_run.thread is not caller
                else None
            )
        if callback_run_to_join is not None:
            joined_thread = callback_run_to_join.thread
            self._join_callback_run(callback_run_to_join)
            with self._lock:
                if (
                    self._callback_run is callback_run_to_join
                    and callback_run_to_join.thread is joined_thread
                ):
                    callback_run_to_join.thread = None

    def bias(self) -> None:
        try:
            self._native.bias()
        except _native.ValidationError as error:
            raise ConfigurationError(str(error)) from error
        except _native.NotConnectedError as error:
            raise NotConnectedError(str(error)) from error

    def wait_for_first_sample(self, timeout: float) -> bool:
        try:
            return bool(self._native.wait_for_first_sample(timeout))
        except _native.ValidationError as error:
            raise ConfigurationError(str(error)) from error
        except _native.NotConnectedError as error:
            raise NotConnectedError(str(error)) from error

    def samples(self, timeout: float | None = None) -> Iterator[Sample]:
        with self._lock:
            if self._constructor_callback is not None or self._mode == "callback":
                raise RuntimeError("callback and iterator delivery are mutually exclusive")
            if self._mode is None:
                self._mode = "iterator"
            run_token = self._run_token
        return self._iterate_samples(timeout, run_token)

    def latest_sample(self) -> Sample | None:
        value = self._native.latest_sample()
        return None if value is None else to_sample(value)

    def health(self) -> Health:
        return to_health(self._native.health(), self._native.queue_dropped_count())

    def wait(self, timeout: float | None = None) -> None:
        with self._lock:
            callback_run = self._callback_run
            if callback_run is None or self._mode == "iterator":
                raise RuntimeError("wait is only available for callback delivery")
        if callback_run.thread is current_thread() and not callback_run.completed.is_set():
            raise RuntimeError("a callback dispatcher cannot wait for itself")
        if not callback_run.completed.wait(timeout):
            raise TimeoutError("timed out waiting for callback delivery to stop")
        self._join_callback_run(callback_run)
        self._raise_callback_run_failure(callback_run)

    def raise_if_failed(self) -> None:
        with self._lock:
            callback_run = self._callback_run
        if callback_run is not None:
            self._raise_callback_run_failure(callback_run)

    def _iterate_samples(self, timeout: float | None, run_token: int) -> Iterator[Sample]:
        while self._iterator_is_current(run_token):
            try:
                result = self._native.read(timeout)
            except _native.ValidationError as error:
                raise ConfigurationError(str(error)) from error
            if not self._iterator_is_current(run_token):
                return
            if result.status == _native.ReadStatus.SAMPLE:
                if result.sample is None:
                    raise RuntimeError("native sample result contains no sample")
                yield to_sample(result.sample)
                continue
            if result.status == _native.ReadStatus.TIMEOUT:
                raise TimeoutError("timed out waiting for a force/torque sample")
            if result.status == _native.ReadStatus.CLOSED:
                fault_error = self._fault_error_for_closed_run(run_token)
                if fault_error is not None:
                    raise fault_error
                return
            raise RuntimeError("native client returned an unknown read status")

    def _iterator_is_current(self, run_token: int) -> bool:
        with self._lock:
            return self._iterator_is_current_locked(run_token)

    def _iterator_is_current_locked(self, run_token: int) -> bool:
        return self._running and self._mode == "iterator" and self._run_token == run_token

    def _fault_error_for_closed_run(self, run_token: int) -> SensorFaultError | None:
        with self._lock:
            if not self._iterator_is_current_locked(run_token):
                return None
            if not self._native.faulted():
                return None
            native_health = self._native.health()
            queue_dropped_count = self._native.queue_dropped_count()
            native_fault_code = self._native.fault_code()
            health = to_health(native_health, queue_dropped_count)
            fault_code = to_fault_code(native_fault_code)
            self._stop_locked()
            return SensorFaultError(fault_code, health)

    def _start_locked(
        self,
        requested_mode: _Mode,
        callback: Callable[[Sample], None] | None,
    ) -> _CallbackStartFailure | None:
        if requested_mode == "iterator":
            self._start_iterator_locked()
            return None
        if callback is None:
            raise RuntimeError("callback delivery requires a callback")
        return self._start_callback_locked(callback)

    def _start_iterator_locked(self) -> None:
        previous_run = self._callback_run
        previous_token = self._run_token
        try:
            try:
                self._native.start()
            except _native.ValidationError as error:
                raise ConfigurationError(str(error)) from error
            except _native.DiscoveryError as error:
                raise DiscoveryError(str(error)) from error
            except _native.NotConnectedError as error:
                raise NotConnectedError(str(error)) from error
            self._running = True
            self._mode = "iterator"
            self._run_token = previous_token + 1
            self._callback_run = None
        except BaseException:
            self._running = False
            self._mode = None
            self._run_token = previous_token
            self._callback_run = previous_run
            with suppress(BaseException):
                self._native.stop()
            raise

    def _start_callback_locked(
        self, callback: Callable[[Sample], None]
    ) -> _CallbackStartFailure | None:
        previous_run = self._callback_run
        previous_token = self._run_token
        callback_run: _CallbackRun | None = None
        try:
            callback_run = _CallbackRun(previous_token + 1, callback)
            dispatcher = Thread(
                target=Client._dispatch_callback,
                args=(ref(self), ref(callback_run)),
                name=f"pynetft-callback-{callback_run.token}",
                daemon=False,
            )
            callback_run.thread = dispatcher
        except BaseException as error:
            if callback_run is not None:
                callback_run.activation.cancel()
                callback_run.callback = None
                callback_run.completed.set()
            return _CallbackStartFailure(
                error,
                error.__traceback__,
                callback_run,
                join_dispatcher=False,
            )

        try:
            dispatcher.start()
        except BaseException as error:
            callback_run.activation.cancel()
            callback_run.callback = None
            return _CallbackStartFailure(
                error,
                error.__traceback__,
                callback_run,
                join_dispatcher=False,
            )

        try:
            try:
                self._native.start()
            except _native.ValidationError as error:
                raise ConfigurationError(str(error)) from error
            except _native.DiscoveryError as error:
                raise DiscoveryError(str(error)) from error
            except _native.NotConnectedError as error:
                raise NotConnectedError(str(error)) from error

            self._running = True
            self._mode = "callback"
            self._run_token = callback_run.token
            self._callback_run = callback_run
            callback_run.activation.activate()
            return None
        except BaseException as error:
            self._running = False
            self._mode = None
            self._run_token = previous_token
            self._callback_run = previous_run
            callback_run.activation.cancel()
            callback_run.callback = None
            with suppress(BaseException):
                self._native.stop()
            return _CallbackStartFailure(
                error,
                error.__traceback__,
                callback_run,
                join_dispatcher=True,
            )

    def _finish_failed_callback_start(self, start_failure: _CallbackStartFailure) -> None:
        if start_failure.join_dispatcher:
            self._join_callback_run(start_failure.callback_run)
        raise start_failure.error.with_traceback(start_failure.traceback)

    @staticmethod
    def _dispatch_callback(
        client_reference: ReferenceType[Client],
        callback_run_reference: ReferenceType[_CallbackRun],
    ) -> None:
        native = None
        try:
            callback_run = callback_run_reference()
            if callback_run is None:
                return
            activation = callback_run.activation
            del callback_run
            if not activation.wait():
                return

            while True:
                client = client_reference()
                callback_run = callback_run_reference()
                if client is None or callback_run is None:
                    return
                if not client._callback_run_is_current(callback_run):
                    return
                native = client._native
                del callback_run
                del client

                result = native.read(None)

                client = client_reference()
                callback_run = callback_run_reference()
                if client is None or callback_run is None:
                    return
                if not client._callback_run_is_current(callback_run):
                    return
                if result.status == _native.ReadStatus.SAMPLE:
                    if result.sample is None:
                        raise RuntimeError("native sample result contains no sample")
                    sample = to_sample(result.sample)
                    if not client._callback_run_is_current(callback_run):
                        return
                    callback = callback_run.callback
                    if callback is None:
                        return
                    try:
                        callback(sample)
                    except BaseException as error:
                        client._record_callback_error(callback_run, error)
                        return
                    del callback
                    del callback_run
                    del client
                    continue
                if result.status == _native.ReadStatus.TIMEOUT:
                    del callback_run
                    del client
                    continue
                if result.status == _native.ReadStatus.CLOSED:
                    client._finish_callback_closed(callback_run)
                    return
                raise RuntimeError("native client returned an unknown read status")
        except _native.ValidationError as error:
            translated = ConfigurationError(str(error))
            translated.__cause__ = error
            client = client_reference()
            callback_run = callback_run_reference()
            if client is not None and callback_run is not None:
                client._record_dispatch_failure(callback_run, translated)
            elif native is not None:
                native.stop()
        except BaseException as error:
            client = client_reference()
            callback_run = callback_run_reference()
            if client is not None and callback_run is not None:
                client._record_dispatch_failure(callback_run, error)
            elif native is not None:
                native.stop()
        finally:
            callback_run = callback_run_reference()
            if callback_run is not None:
                callback_run.callback = None
                callback_run.completed.set()

    def _callback_run_is_current(self, callback_run: _CallbackRun) -> bool:
        with self._lock:
            return self._callback_run_is_current_locked(callback_run)

    def _callback_run_is_current_locked(self, callback_run: _CallbackRun) -> bool:
        return (
            self._running
            and self._mode == "callback"
            and self._run_token == callback_run.token
            and self._callback_run is callback_run
        )

    def _record_callback_error(self, callback_run: _CallbackRun, error: BaseException) -> None:
        with self._lock:
            if callback_run.callback_error is None and callback_run.failure is None:
                callback_run.callback_error = error
            if self._callback_run_is_current_locked(callback_run):
                self._stop_locked()

    def _record_dispatch_failure(self, callback_run: _CallbackRun, error: BaseException) -> None:
        with self._lock:
            if callback_run.callback_error is None and callback_run.failure is None:
                callback_run.callback_error = error
            if self._callback_run_is_current_locked(callback_run):
                self._stop_locked()

    def _finish_callback_closed(self, callback_run: _CallbackRun) -> None:
        with self._lock:
            if not self._callback_run_is_current_locked(callback_run):
                return
            if self._native.faulted():
                native_health = self._native.health()
                queue_dropped_count = self._native.queue_dropped_count()
                native_fault_code = self._native.fault_code()
                health = to_health(native_health, queue_dropped_count)
                fault_code = to_fault_code(native_fault_code)
                callback_run.failure = SensorFaultError(fault_code, health)
            self._stop_locked()

    @staticmethod
    def _join_callback_run(callback_run: _CallbackRun | None) -> None:
        if callback_run is None:
            return
        thread = callback_run.thread
        if thread is None or thread is current_thread():
            return
        thread.join()

    @staticmethod
    def _raise_callback_run_failure(callback_run: _CallbackRun) -> None:
        if callback_run.callback_error is not None:
            raise CallbackError("sample callback failed") from (callback_run.callback_error)
        if callback_run.failure is not None:
            raise callback_run.failure

    def _stop_locked(self) -> None:
        if not self._running:
            return
        self._running = False
        self._native.stop()
        self._mode = None
