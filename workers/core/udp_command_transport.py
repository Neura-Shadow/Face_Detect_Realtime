"""Phase 13B UDP transport for Phase 13A command packets and JILA ACK packets.

Wire rules enforced here:

* One UDP datagram carries exactly one **unchanged** Phase 13A 64-byte command
  packet. No wrapper, no JSON, no extra header. A datagram of any other size is
  an error.
* One UDP datagram carries exactly one 48-byte ``JILA`` ACK/status packet.
* Both receivers can optionally pin the expected source host.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, Optional, Tuple

from .embedded_command_bridge import PACKET_SIZE as COMMAND_PACKET_SIZE
from .jil_protocol import (
    ACK_PACKET_SIZE,
    TRANSPORT_TIMEOUT,
    AckStatusPacket,
    JilProtocolError,
    decode_ack_packet,
    encode_ack_packet,
)

DEFAULT_COMMAND_PORT = 13511
DEFAULT_ACK_PORT = 13512
DEFAULT_UDP_TIMEOUT_SEC = 1.0
#: Bounded receive size: one byte larger than the largest legal datagram so an
#: oversized datagram is detected rather than silently truncated.
_COMMAND_RECV_SIZE = COMMAND_PACKET_SIZE + 1
_ACK_RECV_SIZE = ACK_PACKET_SIZE + 1


class UdpTransportError(RuntimeError):
    """UDP transport failure with a fault-matrix classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


class CommandUdpSender:
    """Jetson side: send unchanged Phase 13A command packets to the PC."""

    def __init__(self, pc_host: str, command_port: int = DEFAULT_COMMAND_PORT) -> None:
        self.pc_host = pc_host
        self.command_port = int(command_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packets_sent = 0
        self.bytes_sent = 0

    def send_command(self, packet_bytes: bytes) -> None:
        if len(packet_bytes) != COMMAND_PACKET_SIZE:
            raise UdpTransportError(
                "LENGTH_REJECT",
                "command datagram must be %d bytes, got %d"
                % (COMMAND_PACKET_SIZE, len(packet_bytes)),
            )
        self._sock.sendto(packet_bytes, (self.pc_host, self.command_port))
        self.packets_sent += 1
        self.bytes_sent += len(packet_bytes)

    def send_raw(self, data: bytes) -> None:
        """Send a deliberately malformed datagram (fault injection only)."""

        self._sock.sendto(data, (self.pc_host, self.command_port))
        self.packets_sent += 1
        self.bytes_sent += len(data)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def metrics(self) -> Dict[str, Any]:
        return {
            "command_packets_sent": self.packets_sent,
            "command_bytes_sent": self.bytes_sent,
        }


class CommandUdpReceiver:
    """PC side: receive Phase 13A command datagrams for the C Virtual Safety MCU."""

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        command_port: int = DEFAULT_COMMAND_PORT,
        *,
        timeout_sec: float = DEFAULT_UDP_TIMEOUT_SEC,
        expected_source_host: Optional[str] = None,
    ) -> None:
        self.bind_host = bind_host
        self.command_port = int(command_port)
        self.expected_source_host = expected_source_host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, self.command_port))
        self._sock.settimeout(float(timeout_sec))
        self.command_port = int(self._sock.getsockname()[1])
        self.datagrams_received = 0
        self.wrong_size_count = 0
        self.unexpected_sender_count = 0

    @property
    def port(self) -> int:
        return self.command_port

    def settimeout(self, timeout_sec: float) -> None:
        self._sock.settimeout(float(timeout_sec))

    def receive(self, *, timeout_sec: Optional[float] = None) -> Tuple[bytes, Tuple[str, int]]:
        """Receive one command datagram, enforcing size and source host."""

        if timeout_sec is not None:
            self._sock.settimeout(float(timeout_sec))
        try:
            data, addr = self._sock.recvfrom(_COMMAND_RECV_SIZE)
        except socket.timeout as exc:
            raise UdpTransportError(TRANSPORT_TIMEOUT, "timeout waiting for command datagram") from exc
        self.datagrams_received += 1
        if self.expected_source_host and addr[0] != self.expected_source_host:
            self.unexpected_sender_count += 1
            raise UdpTransportError(
                "UNEXPECTED_SENDER", "command datagram from unexpected host %s" % (addr[0],)
            )
        if len(data) != COMMAND_PACKET_SIZE:
            self.wrong_size_count += 1
            raise UdpTransportError(
                "LENGTH_REJECT",
                "command datagram size %d is not %d" % (len(data), COMMAND_PACKET_SIZE),
            )
        return data, (str(addr[0]), int(addr[1]))

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def metrics(self) -> Dict[str, Any]:
        return {
            "command_datagrams_received": self.datagrams_received,
            "command_wrong_size_count": self.wrong_size_count,
            "command_unexpected_sender_count": self.unexpected_sender_count,
        }


class AckUdpSender:
    """PC side: send fixed-size JILA ACK/status packets back to the Jetson."""

    def __init__(self, jetson_host: str, ack_port: int = DEFAULT_ACK_PORT) -> None:
        self.jetson_host = jetson_host
        self.ack_port = int(ack_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.acks_sent = 0
        self.acks_dropped = 0

    def send_ack(self, packet: AckStatusPacket, *, drop: bool = False) -> Optional[bytes]:
        """Encode and send an ACK. ``drop=True`` injects a deterministic ACK loss."""

        encoded = encode_ack_packet(packet)
        if drop:
            self.acks_dropped += 1
            return None
        self._sock.sendto(encoded, (self.jetson_host, self.ack_port))
        self.acks_sent += 1
        return encoded

    def send_raw(self, data: bytes) -> None:
        """Send a deliberately corrupted ACK datagram (fault injection only)."""

        self._sock.sendto(data, (self.jetson_host, self.ack_port))
        self.acks_sent += 1

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def metrics(self) -> Dict[str, Any]:
        return {"acks_sent": self.acks_sent, "acks_dropped_injected": self.acks_dropped}


class AckUdpReceiver:
    """Jetson side: validate returning ACK/status packets."""

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        ack_port: int = DEFAULT_ACK_PORT,
        *,
        timeout_sec: float = DEFAULT_UDP_TIMEOUT_SEC,
        expected_source_host: Optional[str] = None,
    ) -> None:
        self.expected_source_host = expected_source_host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, int(ack_port)))
        self._sock.settimeout(float(timeout_sec))
        self.ack_port = int(self._sock.getsockname()[1])
        self.acks_received = 0
        self.valid_acks = 0
        self.crc_reject_count = 0
        self.protocol_reject_count = 0
        self.size_reject_count = 0
        self.sequence_mismatch_count = 0
        self.stale_ack_count = 0
        self.unexpected_sender_count = 0
        self.timeout_count = 0
        self._last_acked_sequence = -1

    @property
    def port(self) -> int:
        return self.ack_port

    def settimeout(self, timeout_sec: float) -> None:
        self._sock.settimeout(float(timeout_sec))

    def receive_ack(
        self,
        *,
        expected_sequence: Optional[int] = None,
        timeout_sec: Optional[float] = None,
    ) -> AckStatusPacket:
        """Receive and fully validate one ACK/status packet."""

        if timeout_sec is not None:
            self._sock.settimeout(float(timeout_sec))
        try:
            data, addr = self._sock.recvfrom(_ACK_RECV_SIZE)
        except socket.timeout as exc:
            self.timeout_count += 1
            raise UdpTransportError(TRANSPORT_TIMEOUT, "timeout waiting for ACK datagram") from exc
        self.acks_received += 1
        if self.expected_source_host and addr[0] != self.expected_source_host:
            self.unexpected_sender_count += 1
            raise UdpTransportError(
                "UNEXPECTED_SENDER", "ACK datagram from unexpected host %s" % (addr[0],)
            )
        if len(data) != ACK_PACKET_SIZE:
            self.size_reject_count += 1
            raise UdpTransportError(
                "ACK_REJECT", "ACK datagram size %d is not %d" % (len(data), ACK_PACKET_SIZE)
            )
        try:
            packet = decode_ack_packet(data)
        except JilProtocolError as exc:
            if exc.classification == "CRC_REJECT":
                self.crc_reject_count += 1
            else:
                self.protocol_reject_count += 1
            raise
        if expected_sequence is not None and packet.acked_sequence != expected_sequence:
            self.sequence_mismatch_count += 1
            raise UdpTransportError(
                "SEQUENCE_REJECT",
                "ACK sequence %d does not match expected %d"
                % (packet.acked_sequence, expected_sequence),
            )
        # Only accepted ACKs carry a monotonic sequence: a rejected command can
        # legitimately report sequence 0 (CRC/length reject), which must not be
        # misclassified as a stale ACK.
        if packet.accepted:
            if packet.acked_sequence < self._last_acked_sequence:
                self.stale_ack_count += 1
                raise UdpTransportError(
                    "STALE_REJECT",
                    "stale ACK sequence %d below last %d"
                    % (packet.acked_sequence, self._last_acked_sequence),
                )
            self._last_acked_sequence = packet.acked_sequence
        self.valid_acks += 1
        return packet

    def drain(self, *, max_packets: int = 64) -> int:
        """Discard any queued ACKs (used when resynchronising a session)."""

        drained = 0
        self._sock.settimeout(0.0)
        try:
            while drained < max_packets:
                try:
                    self._sock.recvfrom(_ACK_RECV_SIZE)
                    drained += 1
                except (socket.timeout, BlockingIOError):
                    break
                except OSError:
                    break
        finally:
            self._sock.settimeout(DEFAULT_UDP_TIMEOUT_SEC)
        return drained

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def metrics(self) -> Dict[str, Any]:
        return {
            "acks_received": self.acks_received,
            "valid_acks_received": self.valid_acks,
            "ack_crc_reject_count": self.crc_reject_count,
            "ack_protocol_reject_count": self.protocol_reject_count,
            "ack_size_reject_count": self.size_reject_count,
            "ack_sequence_mismatch_count": self.sequence_mismatch_count,
            "ack_stale_count": self.stale_ack_count,
            "ack_unexpected_sender_count": self.unexpected_sender_count,
            "ack_timeout_count": self.timeout_count,
        }
