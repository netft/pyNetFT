from __future__ import annotations

import socket
import struct
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition, Event, Lock, Thread
from time import monotonic
from typing import Any

import pytest

STOP_STREAMING = 0x0000
START_REALTIME = 0x0002
BIAS = 0x0042

_REQUEST = struct.Struct(">HHI")
_RECORD = struct.Struct(">III6i")
_MAGIC = 0x1234
_SHUTDOWN = b"pynetft-fake-sensor-shutdown"
_HTTP_HANDLER_DRAIN_TIMEOUT = 0.25


def record(
    rdt_sequence: int,
    ft_sequence: int,
    status: int,
    axes: tuple[int, int, int, int, int, int],
) -> bytes:
    return _RECORD.pack(rdt_sequence, ft_sequence, status, *axes)


@dataclass(frozen=True)
class _Configuration:
    product_name: str = "ATI Net F/T"
    counts_per_force: float = 1_000_000
    counts_per_torque: float = 1_000_000
    force_unit: str = "N"
    torque_unit: str = "N-m"

    def xml(self) -> bytes:
        return (
            '<?xml version="1.0"?>'
            "<netft>"
            f"<prodname>{escape(self.product_name)}</prodname>"
            f"<cfgcpf>{self.counts_per_force}</cfgcpf>"
            f"<cfgcpt>{self.counts_per_torque}</cfgcpt>"
            f"<scfgfu>{escape(self.force_unit)}</scfgfu>"
            f"<scfgtu>{escape(self.torque_unit)}</scfgtu>"
            "</netft>"
        ).encode("ascii")


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        sensor: FakeSensor = self.fake_sensor
        token = id(request)
        sensor._http_handler_started(token)
        try:
            super().process_request(request, client_address)
        except BaseException:
            sensor._http_handler_finished(token)
            raise

    def process_request_thread(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            sensor: FakeSensor = self.fake_sensor
            sensor._http_handler_finished(id(request))

    def handle_error(self, request: object, client_address: tuple[str, int]) -> None:
        del request, client_address
        error = sys.exc_info()[1]
        if error is None:
            error = RuntimeError("HTTP request handler failed")
        sensor: FakeSensor = self.fake_sensor
        sensor._record_background_error(error)


class _ConfigurationHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        sensor: FakeSensor = self.server.fake_sensor
        status, body = sensor._http_response(self.path)
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class FakeSensor:
    host = "127.0.0.1"

    def __init__(self) -> None:
        self._condition = Condition(Lock())
        self._close_lock = Lock()
        self._closed = Event()
        self._configuration = _Configuration()
        self._configuration_on_start: dict[int, _Configuration] = {}
        self._http_status = 200
        self._http_request_count = 0
        self._commands: list[int] = []
        self._requests: list[tuple[int, int, int]] = []
        self._packets_on_start: dict[int, list[bytes]] = {}
        self._start_count = 0
        self._active_start = 0
        self._client_address: tuple[str, int] | None = None
        self._active_http_handlers: set[int] = set()
        self._next_rdt_sequence = 1
        self._next_ft_sequence = 1
        self._background_errors: list[BaseException] = []

        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_socket.bind((self.host, 0))
        self.rdt_port = int(self._udp_socket.getsockname()[1])

        self._http_server = _LoopbackHTTPServer((self.host, 0), _ConfigurationHandler)
        self._http_server.fake_sensor = self
        self.http_port = int(self._http_server.server_address[1])

        self._udp_thread = Thread(
            target=self._serve_udp,
            name=f"fake-netft-udp-{self.rdt_port}",
            daemon=False,
        )
        self._http_thread = Thread(
            target=self._http_server.serve_forever,
            kwargs={"poll_interval": 0.01},
            name=f"fake-netft-http-{self.http_port}",
            daemon=False,
        )
        self._udp_thread.start()
        self._http_thread.start()

    @property
    def commands(self) -> tuple[int, ...]:
        with self._condition:
            return tuple(self._commands)

    @property
    def requests(self) -> tuple[tuple[int, int, int], ...]:
        with self._condition:
            return tuple(self._requests)

    @property
    def http_request_count(self) -> int:
        with self._condition:
            return self._http_request_count

    def configure(
        self,
        *,
        product_name: str = "ATI Net F/T",
        counts_per_force: float = 1_000_000,
        counts_per_torque: float = 1_000_000,
        force_unit: str = "N",
        torque_unit: str = "N-m",
    ) -> None:
        with self._condition:
            self._configuration = _Configuration(
                product_name=product_name,
                counts_per_force=counts_per_force,
                counts_per_torque=counts_per_torque,
                force_unit=force_unit,
                torque_unit=torque_unit,
            )

    def configure_on_start(self, start_count: int, **changes: Any) -> None:
        if start_count < 1:
            raise ValueError("start_count must be positive")
        with self._condition:
            self._configuration_on_start[start_count] = replace(self._configuration, **changes)

    def respond_to_http_with(self, status: int) -> None:
        with self._condition:
            self._http_status = status

    def queue_record(
        self,
        axes: tuple[int, int, int, int, int, int],
        *,
        rdt_sequence: int | None = None,
        ft_sequence: int | None = None,
        status: int = 0,
        on_start: int = 1,
    ) -> None:
        with self._condition:
            selected_rdt = self._next_rdt_sequence if rdt_sequence is None else rdt_sequence
            selected_ft = self._next_ft_sequence if ft_sequence is None else ft_sequence
            self._next_rdt_sequence = selected_rdt + 1
            self._next_ft_sequence = selected_ft + 1
        self.queue_packet(
            record(selected_rdt, selected_ft, status, axes),
            on_start=on_start,
        )

    def queue_malformed(
        self, payload: bytes = b"malformed", *, repeat: int = 1, on_start: int = 1
    ) -> None:
        if repeat < 1:
            raise ValueError("repeat must be positive")
        for _ in range(repeat):
            self.queue_packet(payload, on_start=on_start)

    def queue_packet(self, payload: bytes, *, on_start: int = 1) -> None:
        if on_start < 1:
            raise ValueError("on_start must be positive")
        destination: tuple[str, int] | None = None
        with self._condition:
            self._raise_background_error()
            if on_start == self._active_start and self._client_address is not None:
                destination = self._client_address
            else:
                self._packets_on_start.setdefault(on_start, []).append(payload)
        if destination is not None:
            self._udp_socket.sendto(payload, destination)

    def wait_for_command(self, command: int, *, count: int = 1, timeout: float) -> bool:
        deadline = monotonic() + timeout
        with self._condition:
            while self._commands.count(command) < count:
                self._raise_background_error()
                remaining = deadline - monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True

    def wait_for_http_requests(self, count: int, *, timeout: float) -> bool:
        deadline = monotonic() + timeout
        with self._condition:
            while self._http_request_count < count:
                self._raise_background_error()
                remaining = deadline - monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self) -> None:
        with self._close_lock:
            if not self._closed.is_set():
                self._closed.set()
                self._http_server.shutdown()
                self._http_server.server_close()

                wakeup = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    wakeup.sendto(_SHUTDOWN, (self.host, self.rdt_port))
                finally:
                    wakeup.close()

                self._http_thread.join(2.0)
                self._udp_thread.join(2.0)
                self._udp_socket.close()
                if self._http_thread.is_alive() or self._udp_thread.is_alive():
                    raise RuntimeError("fake sensor server thread did not stop")

            self._wait_for_http_handlers(_HTTP_HANDLER_DRAIN_TIMEOUT)
            self._raise_background_error()

    def _http_response(self, path: str) -> tuple[int, bytes]:
        with self._condition:
            self._http_request_count += 1
            self._condition.notify_all()
            if path != "/netftapi2.xml":
                return 404, b""
            status = self._http_status
            body = self._configuration.xml() if status == 200 else b""
            return status, body

    def _serve_udp(self) -> None:
        try:
            while True:
                payload, address = self._udp_socket.recvfrom(65_536)
                if self._closed.is_set() and payload == _SHUTDOWN:
                    return
                if len(payload) != _REQUEST.size:
                    continue
                magic, command, count = _REQUEST.unpack(payload)
                if magic != _MAGIC:
                    continue

                packets: tuple[bytes, ...] = ()
                with self._condition:
                    self._requests.append((magic, command, count))
                    self._commands.append(command)
                    if command == START_REALTIME:
                        self._start_count += 1
                        self._active_start = self._start_count
                        self._client_address = address
                        if self._start_count in self._configuration_on_start:
                            self._configuration = self._configuration_on_start.pop(
                                self._start_count
                            )
                        packets = tuple(self._packets_on_start.pop(self._start_count, ()))
                    elif command == STOP_STREAMING:
                        self._client_address = None
                        self._active_start = 0
                    self._condition.notify_all()

                for packet in packets:
                    self._udp_socket.sendto(packet, address)
        except BaseException as error:
            if not self._closed.is_set():
                with self._condition:
                    self._background_errors.append(error)
                    self._condition.notify_all()

    def _raise_background_error(self) -> None:
        if self._background_errors:
            raise self._background_errors.pop(0)

    def _record_background_error(self, error: BaseException) -> None:
        with self._condition:
            self._background_errors.append(error)
            self._condition.notify_all()

    def _http_handler_started(self, token: int) -> None:
        with self._condition:
            self._active_http_handlers.add(token)
            self._condition.notify_all()

    def _http_handler_finished(self, token: int) -> None:
        with self._condition:
            self._active_http_handlers.discard(token)
            self._condition.notify_all()

    def _wait_for_http_handlers(self, timeout: float) -> None:
        deadline = monotonic() + timeout
        with self._condition:
            while self._active_http_handlers:
                remaining = deadline - monotonic()
                if remaining <= 0.0:
                    raise TimeoutError("fake sensor HTTP handlers did not stop")
                self._condition.wait(remaining)

    def __enter__(self) -> FakeSensor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


@pytest.fixture
def fake_sensor() -> Iterator[FakeSensor]:
    sensor = FakeSensor()
    try:
        yield sensor
    finally:
        sensor.close()
