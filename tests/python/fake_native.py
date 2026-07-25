from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition, Event
from time import monotonic
from types import SimpleNamespace

from pynetft import _native


@dataclass(frozen=True)
class FakeReadResult:
    status: _native.ReadStatus
    sample: object | None = None


class FakeNativeClient:
    def __init__(self, config: object, queue_size: int) -> None:
        self.config = config
        self.queue_size = queue_size
        self.started = False
        self.stopped = False
        self.start_count = 0
        self.stop_count = 0
        self.bias_count = 0
        self.read_count = 0
        self.start_error: BaseException | None = None
        self.health_value = SimpleNamespace()
        self.faulted_value = False
        self.fault_code_value = _native.FaultCode.NONE
        self.dropped_value = 0
        self._generation = 0
        self._samples: deque[object] = deque()
        self._condition = Condition()
        self._pause_read_after_wake = False
        self._read_paused = False
        self._pause_fault_inspection = False
        self._fault_inspection_entered = Event()
        self._fault_inspection_release = Event()

    def start(self) -> None:
        with self._condition:
            self.start_count += 1
            if self.start_error is not None:
                raise self.start_error
            self._generation += 1
            self._samples.clear()
            self.dropped_value = 0
            self.faulted_value = False
            self.fault_code_value = _native.FaultCode.NONE
            self.started = True
            self.stopped = False
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self.stop_count += 1
            self._generation += 1
            self.stopped = True
            self._condition.notify_all()

    def bias(self) -> None:
        if not self.started or self.stopped:
            raise _native.NotConnectedError()
        self.bias_count += 1

    def wait_for_first_sample(self, timeout: float) -> bool:
        deadline = monotonic() + timeout
        with self._condition:
            generation = self._generation
            while not self._samples and not self.stopped and generation == self._generation:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return generation == self._generation and not self.stopped and bool(self._samples)

    def read(self, timeout: float | None) -> FakeReadResult:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            generation = self._generation
            self.read_count += 1
            self._condition.notify_all()
            while not self._samples and not self.stopped and generation == self._generation:
                if deadline is None:
                    self._condition.wait()
                else:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return FakeReadResult(_native.ReadStatus.TIMEOUT)
                    self._condition.wait(remaining)
            if self._pause_read_after_wake:
                self._read_paused = True
                self._condition.notify_all()
                self._condition.wait_for(lambda: not self._pause_read_after_wake)
            if generation != self._generation or self.stopped:
                return FakeReadResult(_native.ReadStatus.CLOSED)
            if self._samples:
                return FakeReadResult(_native.ReadStatus.SAMPLE, self._samples.popleft())
            return FakeReadResult(_native.ReadStatus.CLOSED)

    def latest_sample(self) -> object | None:
        with self._condition:
            return self._samples[-1] if self._samples else None

    def health(self) -> object:
        return self.health_value

    def faulted(self) -> bool:
        if self._pause_fault_inspection:
            self._fault_inspection_entered.set()
            self._fault_inspection_release.wait()
            self._pause_fault_inspection = False
        return self.faulted_value

    def fault_code(self) -> object:
        return self.fault_code_value

    def queue_dropped_count(self) -> int:
        return self.dropped_value

    def queue(self, sample: object) -> None:
        with self._condition:
            if not self.started or self.stopped:
                return
            self._samples.append(sample)
            self._condition.notify_all()

    def wait_until_read(self, timeout: float = 1.0) -> bool:
        deadline = monotonic() + timeout
        with self._condition:
            while self.read_count == 0:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def pause_next_read_after_wake(self) -> None:
        with self._condition:
            self._pause_read_after_wake = True
            self._read_paused = False

    def wait_until_read_paused(self, timeout: float = 1.0) -> bool:
        deadline = monotonic() + timeout
        with self._condition:
            while not self._read_paused:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def release_paused_read(self) -> None:
        with self._condition:
            self._pause_read_after_wake = False
            self._condition.notify_all()

    def pause_fault_inspection(self) -> None:
        self._fault_inspection_entered.clear()
        self._fault_inspection_release.clear()
        self._pause_fault_inspection = True

    def wait_until_fault_inspection(self, timeout: float = 1.0) -> bool:
        return self._fault_inspection_entered.wait(timeout)

    def release_fault_inspection(self) -> None:
        self._fault_inspection_release.set()
