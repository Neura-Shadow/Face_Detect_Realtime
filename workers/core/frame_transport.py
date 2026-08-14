"""Phase 13B TCP frame transport (simulation PC -> real Jetson).

Bounded, timeout-driven TCP transport for ``JILF`` frame messages:

* :class:`FrameStreamClient` — PC side. Connects to the Jetson frame server and
  writes ``header + payload`` with partial-write handling and reconnect support.
* :class:`FrameStreamServer` — Jetson side. Accepts one publisher connection at
  a time and reads frames directly into :class:`FixedBufferPool` buffers.

No pickle, no unbounded receive buffer, no dynamic allocation per frame beyond
the fixed pool. Every read/write has a bounded socket timeout.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, Optional, Tuple

from .jil_protocol import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    FRAME_HEADER_SIZE,
    TRANSPORT_TIMEOUT,
    FrameHeader,
    JilProtocolError,
    decode_frame_header,
    verify_frame_payload,
)
from .latest_frame_mailbox import BufferState, FixedBufferPool, PooledBuffer

DEFAULT_FRAME_PORT = 13510
DEFAULT_SOCKET_TIMEOUT_SEC = 5.0


class FrameTransportError(RuntimeError):
    """Transport-level failure with a fault-matrix classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


class FrameTransportClosed(FrameTransportError):
    """Peer closed the connection (clean EOF or mid-message disconnect)."""


def _recv_into_exact(
    sock: socket.socket,
    target: memoryview,
    length: int,
    *,
    what: str,
) -> None:
    """Read exactly ``length`` bytes into ``target`` handling partial TCP reads."""

    received = 0
    while received < length:
        try:
            chunk = sock.recv_into(target[received:length], length - received)
        except socket.timeout as exc:
            raise FrameTransportError(
                TRANSPORT_TIMEOUT, "timeout while reading %s (%d/%d)" % (what, received, length)
            ) from exc
        except OSError as exc:
            raise FrameTransportClosed(
                TRANSPORT_TIMEOUT, "socket error while reading %s: %s" % (what, exc)
            ) from exc
        if chunk == 0:
            raise FrameTransportClosed(
                TRANSPORT_TIMEOUT,
                "peer disconnected while reading %s (%d/%d)" % (what, received, length),
            )
        received += chunk


def _sendall_bounded(sock: socket.socket, payload: bytes, *, what: str) -> None:
    """Write all bytes, converting timeouts into a classified transport error."""

    view = memoryview(payload)
    sent = 0
    total = len(payload)
    while sent < total:
        try:
            written = sock.send(view[sent:])
        except socket.timeout as exc:
            raise FrameTransportError(
                TRANSPORT_TIMEOUT, "timeout while writing %s (%d/%d)" % (what, sent, total)
            ) from exc
        except OSError as exc:
            raise FrameTransportClosed(
                TRANSPORT_TIMEOUT, "socket error while writing %s: %s" % (what, exc)
            ) from exc
        if written == 0:
            raise FrameTransportClosed(TRANSPORT_TIMEOUT, "peer stopped accepting %s" % what)
        sent += written


class FrameStreamClient:
    """PC-side publisher connection to the Jetson frame server."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_FRAME_PORT,
        *,
        timeout_sec: float = DEFAULT_SOCKET_TIMEOUT_SEC,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout_sec = float(timeout_sec)
        self.max_payload_bytes = int(max_payload_bytes)
        self._sock = None  # type: Optional[socket.socket]
        self.connect_count = 0
        self.reconnect_count = 0
        self.frames_sent = 0
        self.bytes_sent = 0
        self.send_failure_count = 0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self, *, timeout_sec: Optional[float] = None) -> None:
        if self._sock is not None:
            return
        deadline = self.timeout_sec if timeout_sec is None else float(timeout_sec)
        sock = socket.create_connection((self.host, self.port), timeout=deadline)
        sock.settimeout(self.timeout_sec)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self.connect_count += 1
        if self.connect_count > 1:
            self.reconnect_count += 1

    def send_frame_message(self, message: bytes) -> None:
        """Send a pre-built ``header + payload`` message."""

        if self._sock is None:
            raise FrameTransportError(TRANSPORT_TIMEOUT, "frame client is not connected")
        try:
            _sendall_bounded(self._sock, message, what="frame")
        except FrameTransportError:
            self.send_failure_count += 1
            self.close()
            raise
        self.frames_sent += 1
        self.bytes_sent += len(message)

    def send_raw(self, data: bytes) -> None:
        """Send arbitrary bytes; used only by deterministic fault injection."""

        if self._sock is None:
            raise FrameTransportError(TRANSPORT_TIMEOUT, "frame client is not connected")
        _sendall_bounded(self._sock, data, what="raw")
        self.bytes_sent += len(data)

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def metrics(self) -> Dict[str, Any]:
        return {
            "frame_client_connect_count": self.connect_count,
            "frame_client_reconnect_count": self.reconnect_count,
            "frame_client_frames_sent": self.frames_sent,
            "frame_client_bytes_sent": self.bytes_sent,
            "frame_client_send_failure_count": self.send_failure_count,
        }


class FrameStreamServer:
    """Jetson-side frame server reading into a bounded fixed buffer pool."""

    def __init__(
        self,
        bind_host: str,
        port: int = DEFAULT_FRAME_PORT,
        *,
        pool: FixedBufferPool,
        timeout_sec: float = DEFAULT_SOCKET_TIMEOUT_SEC,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        expected_peer_host: Optional[str] = None,
    ) -> None:
        self.bind_host = bind_host
        self.port = int(port)
        self.pool = pool
        self.timeout_sec = float(timeout_sec)
        self.max_payload_bytes = int(max_payload_bytes)
        self.expected_peer_host = expected_peer_host
        self._listen_sock = None  # type: Optional[socket.socket]
        self._conn = None  # type: Optional[socket.socket]
        self.peer = None  # type: Optional[Tuple[str, int]]
        self.accept_count = 0
        self.unexpected_peer_reject_count = 0
        self.header_reject_count = 0
        self.payload_reject_count = 0

    def bind(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.port))
        sock.listen(1)
        sock.settimeout(self.timeout_sec)
        self._listen_sock = sock
        self.port = int(sock.getsockname()[1])
        return self.port

    def accept(self, *, timeout_sec: Optional[float] = None) -> Tuple[str, int]:
        """Accept one publisher connection, rejecting unexpected source hosts."""

        if self._listen_sock is None:
            raise FrameTransportError(TRANSPORT_TIMEOUT, "frame server is not bound")
        self._listen_sock.settimeout(self.timeout_sec if timeout_sec is None else float(timeout_sec))
        try:
            conn, addr = self._listen_sock.accept()
        except socket.timeout as exc:
            raise FrameTransportError(TRANSPORT_TIMEOUT, "timeout waiting for frame publisher") from exc
        if self.expected_peer_host and addr[0] != self.expected_peer_host:
            self.unexpected_peer_reject_count += 1
            try:
                conn.close()
            except OSError:
                pass
            raise FrameTransportError(
                TRANSPORT_TIMEOUT, "unexpected frame publisher source host %s" % (addr[0],)
            )
        conn.settimeout(self.timeout_sec)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.close_connection()
        self._conn = conn
        self.peer = (str(addr[0]), int(addr[1]))
        self.accept_count += 1
        return self.peer

    def receive_frame(
        self,
        *,
        timeout_sec: Optional[float] = None,
    ) -> Tuple[FrameHeader, PooledBuffer]:
        """Read one validated frame into a pooled buffer.

        The caller owns the returned buffer and must publish it to the mailbox
        or release it back to the pool. Every rejection path releases the buffer
        before raising, so the bounded pool can never leak.
        """

        if self._conn is None:
            raise FrameTransportError(TRANSPORT_TIMEOUT, "no active frame connection")
        if timeout_sec is not None:
            self._conn.settimeout(float(timeout_sec))

        header_bytes = bytearray(FRAME_HEADER_SIZE)
        _recv_into_exact(self._conn, memoryview(header_bytes), FRAME_HEADER_SIZE, what="frame header")
        try:
            header = decode_frame_header(bytes(header_bytes), max_payload_bytes=self.max_payload_bytes)
        except JilProtocolError:
            self.header_reject_count += 1
            raise

        buffer = self.pool.acquire(BufferState.TRANSPORT_OWNED)
        if buffer is None:
            self._drain(header.payload_size)
            raise FrameTransportError("BUFFER_POOL_EXHAUSTED", "no free buffer for incoming frame")
        if header.payload_size > buffer.capacity:
            self.pool.release(buffer)
            self._drain(header.payload_size)
            raise JilProtocolError("FRAME_SIZE_REJECT", "payload exceeds pooled buffer capacity")

        try:
            _recv_into_exact(self._conn, buffer.view(), header.payload_size, what="frame payload")
            buffer.length = header.payload_size
            verify_frame_payload(header, bytes(buffer.data[: header.payload_size]))
        except JilProtocolError:
            self.payload_reject_count += 1
            self.pool.release(buffer)
            raise
        except FrameTransportError:
            self.pool.release(buffer)
            raise
        buffer.meta = {"header": header}
        return header, buffer

    def _drain(self, length: int) -> None:
        """Discard a payload we cannot buffer, keeping the stream framed."""

        if self._conn is None:
            return
        scratch = bytearray(65536)
        view = memoryview(scratch)
        remaining = length
        while remaining > 0:
            take = min(remaining, len(scratch))
            try:
                _recv_into_exact(self._conn, view, take, what="discarded payload")
            except FrameTransportError:
                return
            remaining -= take

    def close_connection(self) -> None:
        conn = self._conn
        self._conn = None
        self.peer = None
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self.close_connection()
        sock = self._listen_sock
        self._listen_sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def metrics(self) -> Dict[str, Any]:
        return {
            "frame_server_accept_count": self.accept_count,
            "frame_server_unexpected_peer_reject_count": self.unexpected_peer_reject_count,
            "frame_server_header_reject_count": self.header_reject_count,
            "frame_server_payload_reject_count": self.payload_reject_count,
        }


# ── Control / clock / metrics channel (length-prefixed JSON over TCP) ───────

CONTROL_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
_CONTROL_LENGTH_PREFIX = 4


def send_control_message(sock: socket.socket, message: Dict[str, Any]) -> None:
    """Send one length-prefixed UTF-8 JSON control message.

    JSON only: Phase 13B never puts pickle on the wire. The 4-byte big-endian
    length prefix keeps the reader's allocation bounded.
    """

    import json

    encoded = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(encoded) > CONTROL_MAX_MESSAGE_BYTES:
        raise FrameTransportError(
            "FRAME_SIZE_REJECT", "control message exceeds %d bytes" % CONTROL_MAX_MESSAGE_BYTES
        )
    prefix = len(encoded).to_bytes(_CONTROL_LENGTH_PREFIX, "big")
    _sendall_bounded(sock, prefix + encoded, what="control message")


def recv_control_message(sock: socket.socket, *, timeout_sec: Optional[float] = None) -> Dict[str, Any]:
    """Receive one length-prefixed UTF-8 JSON control message."""

    import json

    if timeout_sec is not None:
        sock.settimeout(float(timeout_sec))
    prefix = bytearray(_CONTROL_LENGTH_PREFIX)
    _recv_into_exact(sock, memoryview(prefix), _CONTROL_LENGTH_PREFIX, what="control length")
    length = int.from_bytes(bytes(prefix), "big")
    if length <= 0 or length > CONTROL_MAX_MESSAGE_BYTES:
        raise FrameTransportError("FRAME_SIZE_REJECT", "invalid control message length %d" % length)
    body = bytearray(length)
    _recv_into_exact(sock, memoryview(body), length, what="control body")
    decoded = json.loads(bytes(body).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise FrameTransportError("FRAME_PROTOCOL_REJECT", "control message must be a JSON object")
    return decoded


# ── JPEG codec (shared by the PC publisher and the Jetson receiver) ──────────


class JpegCodecError(RuntimeError):
    """JPEG codec is unavailable or failed on a specific payload."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


class JpegCodec:
    """Explicit BGRA/BGR aware JPEG codec.

    Backend selection order is ``cv2`` then ``PIL``; both are already installed
    in the environments Phase 13B runs on, so no dependency is ever installed
    automatically. Colour handling is explicit on both backends: CARLA delivers
    BGRA, Phase 13B converts BGRA -> BGR before encoding, and the Jetson decodes
    straight back to BGR8. Raw BGRA is never sent while declaring BGR8.
    """

    def __init__(self, *, quality: int = 85, backend: Optional[str] = None) -> None:
        self.quality = int(quality)
        self.backend = "unavailable"
        self.backend_version = ""
        self._cv2 = None  # type: Any
        self._pil_image = None  # type: Any
        self._pil_numpy = None  # type: Any
        self._pil_io = None  # type: Any
        self.error = None  # type: Optional[str]

        if backend in (None, "cv2"):
            try:
                import cv2  # type: ignore[import-not-found]

                self._cv2 = cv2
                self.backend = "cv2"
                self.backend_version = str(getattr(cv2, "__version__", ""))
                return
            except Exception as exc:  # pragma: no cover - environment dependent
                self.error = repr(exc)
        if backend in (None, "pil"):
            try:
                import io

                import numpy
                from PIL import Image  # type: ignore[import-not-found]

                self._pil_image = Image
                self._pil_numpy = numpy
                self._pil_io = io
                self.backend = "pil"
                self.backend_version = str(getattr(Image, "__version__", ""))
                return
            except Exception as exc:  # pragma: no cover - environment dependent
                self.error = repr(exc)

    @property
    def available(self) -> bool:
        return self.backend != "unavailable"

    @staticmethod
    def bgra_to_bgr(array: Any) -> Any:
        """Explicit CARLA BGRA -> BGR conversion (drops the alpha channel)."""

        if array.ndim != 3:
            raise JpegCodecError("FRAME_SIZE_REJECT", "expected an HxWxC array")
        if array.shape[2] == 4:
            return array[:, :, :3]
        if array.shape[2] == 3:
            return array
        raise JpegCodecError("FRAME_SIZE_REJECT", "unsupported channel count %d" % array.shape[2])

    def encode_bgr(self, bgr_array: Any) -> bytes:
        """Encode an HxWx3 BGR8 array into a JPEG payload."""

        if not self.available:
            raise JpegCodecError("jpeg_codec_unavailable", self.error or "no JPEG backend")
        if self.backend == "cv2":
            ok, encoded = self._cv2.imencode(
                ".jpg", bgr_array, [int(self._cv2.IMWRITE_JPEG_QUALITY), self.quality]
            )
            if not ok:
                raise JpegCodecError("FRAME_CODEC_REJECT", "cv2 JPEG encode failed")
            return encoded.tobytes()
        # PIL expects RGB, so the BGR -> RGB reversal is explicit here.
        image = self._pil_image.fromarray(bgr_array[:, :, ::-1])
        buffer = self._pil_io.BytesIO()
        image.save(buffer, format="JPEG", quality=self.quality)
        return buffer.getvalue()

    def decode_to_bgr(self, payload: bytes) -> Any:
        """Decode a JPEG payload back into an HxWx3 BGR8 array."""

        if not self.available:
            raise JpegCodecError("jpeg_codec_unavailable", self.error or "no JPEG backend")
        if self.backend == "cv2":
            import numpy

            buffer = numpy.frombuffer(payload, dtype=numpy.uint8)
            decoded = self._cv2.imdecode(buffer, self._cv2.IMREAD_COLOR)
            if decoded is None:
                raise JpegCodecError("FRAME_CODEC_REJECT", "cv2 JPEG decode failed")
            return decoded
        image = self._pil_image.open(self._pil_io.BytesIO(payload))
        rgb = self._pil_numpy.asarray(image.convert("RGB"))
        return rgb[:, :, ::-1]

    def describe(self) -> Dict[str, Any]:
        return {
            "jpeg_backend": self.backend,
            "jpeg_backend_version": self.backend_version,
            "jpeg_quality": self.quality,
            "jpeg_codec_available": self.available,
            "jpeg_codec_error": self.error,
            "jpeg_auto_install_performed": False,
        }


def jpeg_codec_preflight(*, quality: int = 85) -> Dict[str, Any]:
    """Round-trip a small synthetic frame to prove the JPEG path really works."""

    codec = JpegCodec(quality=quality)
    report = codec.describe()
    report["jpeg_roundtrip_passed"] = False
    report["jpeg_blocker"] = None
    if not codec.available:
        report["jpeg_blocker"] = "jpeg_codec_unavailable"
        return report
    try:
        import numpy

        probe = numpy.zeros((16, 24, 3), dtype=numpy.uint8)
        probe[:, :, 0] = 200  # blue channel in BGR order
        probe[:, :, 2] = 40
        payload = codec.encode_bgr(probe)
        decoded = codec.decode_to_bgr(payload)
        report["jpeg_payload_bytes"] = len(payload)
        report["jpeg_decoded_shape"] = list(decoded.shape)
        blue_dominant = int(decoded[:, :, 0].mean()) > int(decoded[:, :, 2].mean())
        report["jpeg_bgr_channel_order_verified"] = bool(blue_dominant)
        report["jpeg_roundtrip_passed"] = bool(
            decoded.shape == probe.shape and decoded.dtype == probe.dtype and blue_dominant
        )
        if not report["jpeg_roundtrip_passed"]:
            report["jpeg_blocker"] = "jpeg_codec_unavailable"
    except Exception as exc:  # pragma: no cover - environment dependent
        report["jpeg_blocker"] = "jpeg_codec_unavailable"
        report["jpeg_codec_error"] = repr(exc)
    return report
