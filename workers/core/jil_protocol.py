"""Phase 13B Jetson-in-the-loop wire protocols.

This module owns two Phase 13B wire contracts:

1. ``JILF`` frame header — a fixed 56-byte little-endian header that prefixes
   every encoded camera frame sent from the simulation PC to the real Jetson.
2. ``JILA`` ACK/status packet — a fixed 48-byte little-endian packet returned
   by the PC C Virtual Safety MCU to the Jetson after every received command.

The Phase 13A 64-byte command packet is NOT redefined here. Phase 13B reuses
``workers.core.embedded_command_bridge`` unchanged; one UDP datagram carries
exactly one unchanged Phase 13A command packet with no wrapper.

Runtime compatibility: this module must import and run on Jetson Python 3.8.10.
Only ``typing`` generics are used; no 3.9/3.10+ runtime APIs.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional

# ── Shared protocol constants ────────────────────────────────────────────────

JIL_PROTOCOL_VERSION = 1

FRAME_MAGIC = b"JILF"
FRAME_HEADER_SIZE = 56
FRAME_HEADER_STRUCT = struct.Struct("<4sHHHHQQQIIHHII")

ACK_MAGIC = b"JILA"
ACK_PACKET_SIZE = 48
ACK_CRC_OFFSET = 44
ACK_STRUCT = struct.Struct("<4sHHIQQBBBBIIII")

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_FRAME_WIDTH = 8192
MAX_FRAME_HEIGHT = 8192
MAX_FRAME_CHANNELS = 4

if FRAME_HEADER_STRUCT.size != FRAME_HEADER_SIZE:  # pragma: no cover - layout guard
    raise RuntimeError(
        "JILF frame header layout drift: %d != %d" % (FRAME_HEADER_STRUCT.size, FRAME_HEADER_SIZE)
    )
if ACK_STRUCT.size != ACK_PACKET_SIZE:  # pragma: no cover - layout guard
    raise RuntimeError(
        "JILA ack packet layout drift: %d != %d" % (ACK_STRUCT.size, ACK_PACKET_SIZE)
    )


class FrameCodec(IntEnum):
    """Encoded payload codec carried in the frame header."""

    JPEG = 1


class PixelFormat(IntEnum):
    """Declared pixel format of the Jetson-side decoded frame."""

    BGR8 = 1


class FrameFlags(IntEnum):
    """Frame header flag bits."""

    KEYFRAME = 1 << 0
    LAST_FRAME = 1 << 1
    FAULT_INJECTED = 1 << 2


class AckMessageType(IntEnum):
    """ACK/status message classes returned by the PC Virtual Safety MCU."""

    COMMAND_ACK = 1
    STATUS = 2
    SESSION_RESET = 3


class Classification(str):
    """Marker type so classification constants stay readable in evidence."""


ACCEPTED = "ACCEPTED"
CRC_REJECT = "CRC_REJECT"
SEQUENCE_REJECT = "SEQUENCE_REJECT"
STALE_REJECT = "STALE_REJECT"
LEASE_REJECT = "LEASE_REJECT"
RANGE_REJECT = "RANGE_REJECT"
LENGTH_REJECT = "LENGTH_REJECT"
VERSION_REJECT = "VERSION_REJECT"
STATE_REJECT = "STATE_REJECT"
SAFE_STOP = "SAFE_STOP"
FAILSAFE = "FAILSAFE"
TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
CLOCK_SYNC_DEGRADED = "CLOCK_SYNC_DEGRADED"
FRAME_CRC_REJECT = "FRAME_CRC_REJECT"
FRAME_SIZE_REJECT = "FRAME_SIZE_REJECT"
FRAME_PROTOCOL_REJECT = "FRAME_PROTOCOL_REJECT"
FRAME_CODEC_REJECT = "FRAME_CODEC_REJECT"
FRAME_PIXEL_FORMAT_REJECT = "FRAME_PIXEL_FORMAT_REJECT"
ACK_REJECT = "ACK_REJECT"

#: Documented mapping from the Phase 13A C ``protocol_result_t`` enum value to
#: the Phase 13B fault-matrix classification vocabulary. The numeric values are
#: the frozen Phase 13A classifications and must not be reordered.
C_RESULT_CODE_TO_CLASSIFICATION: Dict[int, str] = {
    0: ACCEPTED,
    1: LENGTH_REJECT,
    2: CRC_REJECT,
    3: STALE_REJECT,
    4: SEQUENCE_REJECT,
    5: LEASE_REJECT,
    6: VERSION_REJECT,
    7: RANGE_REJECT,
    8: STATE_REJECT,
}

#: Reverse lookup used by tests and fault-matrix expectation checks.
CLASSIFICATION_TO_C_RESULT_CODE: Dict[str, int] = {
    name: code for code, name in C_RESULT_CODE_TO_CLASSIFICATION.items()
}


def classification_for_result_code(result_code: int) -> str:
    """Map a C ``protocol_result_t`` value onto a Phase 13B classification."""

    return C_RESULT_CODE_TO_CLASSIFICATION.get(int(result_code), "UNKNOWN_RESULT_CODE")


def crc32_iso_hdlc(data: bytes) -> int:
    """CRC-32/ISO-HDLC, identical to the frozen Phase 13A command CRC."""

    return zlib.crc32(data) & 0xFFFFFFFF


class JilProtocolError(ValueError):
    """Phase 13B wire-protocol violation with a fault-matrix classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


# ── JILF frame header ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FrameHeader:
    """Fixed 56-byte little-endian frame header."""

    frame_id: int
    simulation_timestamp_us: int
    pc_monotonic_us: int
    width: int
    height: int
    payload_size: int
    payload_crc32: int
    channels: int = 3
    codec: int = int(FrameCodec.JPEG)
    pixel_format: int = int(PixelFormat.BGR8)
    flags: int = 0
    protocol_version: int = JIL_PROTOCOL_VERSION
    header_size: int = FRAME_HEADER_SIZE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "header_size": self.header_size,
            "flags": self.flags,
            "codec": self.codec,
            "frame_id": self.frame_id,
            "simulation_timestamp_us": self.simulation_timestamp_us,
            "pc_monotonic_us": self.pc_monotonic_us,
            "width": self.width,
            "height": self.height,
            "channels": self.channels,
            "pixel_format": self.pixel_format,
            "payload_size": self.payload_size,
            "payload_crc32": self.payload_crc32,
        }


def encode_frame_header(header: FrameHeader) -> bytes:
    """Serialise a :class:`FrameHeader` into exactly 56 little-endian bytes."""

    encoded = FRAME_HEADER_STRUCT.pack(
        FRAME_MAGIC,
        header.protocol_version,
        header.flags,
        FRAME_HEADER_SIZE,
        header.codec,
        header.frame_id,
        header.simulation_timestamp_us,
        header.pc_monotonic_us,
        header.width,
        header.height,
        header.channels,
        header.pixel_format,
        header.payload_size,
        header.payload_crc32,
    )
    if len(encoded) != FRAME_HEADER_SIZE:  # pragma: no cover - layout guard
        raise RuntimeError("frame header encode drift: %d" % len(encoded))
    return encoded


def decode_frame_header(
    data: bytes,
    *,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
) -> FrameHeader:
    """Decode and validate a 56-byte frame header.

    Raises :class:`JilProtocolError` carrying the fault-matrix classification
    for every rejection path. Allocation stays bounded by ``max_payload_bytes``.
    """

    if len(data) != FRAME_HEADER_SIZE:
        raise JilProtocolError(
            FRAME_SIZE_REJECT, "frame header must be %d bytes, got %d" % (FRAME_HEADER_SIZE, len(data))
        )
    (
        magic,
        protocol_version,
        flags,
        header_size,
        codec,
        frame_id,
        simulation_timestamp_us,
        pc_monotonic_us,
        width,
        height,
        channels,
        pixel_format,
        payload_size,
        payload_crc32,
    ) = FRAME_HEADER_STRUCT.unpack(data)

    if magic != FRAME_MAGIC:
        raise JilProtocolError(FRAME_PROTOCOL_REJECT, "unexpected frame magic %r" % (magic,))
    if protocol_version != JIL_PROTOCOL_VERSION:
        raise JilProtocolError(
            FRAME_PROTOCOL_REJECT, "unsupported frame protocol version %d" % protocol_version
        )
    if header_size != FRAME_HEADER_SIZE:
        raise JilProtocolError(FRAME_PROTOCOL_REJECT, "unsupported header size %d" % header_size)
    if codec != int(FrameCodec.JPEG):
        raise JilProtocolError(FRAME_CODEC_REJECT, "unsupported codec %d" % codec)
    if pixel_format != int(PixelFormat.BGR8):
        raise JilProtocolError(
            FRAME_PIXEL_FORMAT_REJECT, "unsupported pixel format %d" % pixel_format
        )
    if not 0 < width <= MAX_FRAME_WIDTH or not 0 < height <= MAX_FRAME_HEIGHT:
        raise JilProtocolError(FRAME_SIZE_REJECT, "invalid frame dimensions %dx%d" % (width, height))
    if not 0 < channels <= MAX_FRAME_CHANNELS:
        raise JilProtocolError(FRAME_SIZE_REJECT, "invalid channel count %d" % channels)
    if payload_size <= 0:
        raise JilProtocolError(FRAME_SIZE_REJECT, "zero-size payload rejected")
    if payload_size > max_payload_bytes:
        raise JilProtocolError(
            FRAME_SIZE_REJECT,
            "payload %d exceeds configured maximum %d" % (payload_size, max_payload_bytes),
        )

    return FrameHeader(
        frame_id=frame_id,
        simulation_timestamp_us=simulation_timestamp_us,
        pc_monotonic_us=pc_monotonic_us,
        width=width,
        height=height,
        payload_size=payload_size,
        payload_crc32=payload_crc32,
        channels=channels,
        codec=codec,
        pixel_format=pixel_format,
        flags=flags,
        protocol_version=protocol_version,
        header_size=header_size,
    )


def verify_frame_payload(header: FrameHeader, payload: bytes) -> None:
    """Verify payload length and CRC-32/ISO-HDLC over the encoded payload only."""

    if len(payload) != header.payload_size:
        raise JilProtocolError(
            FRAME_SIZE_REJECT,
            "payload length %d does not match declared %d" % (len(payload), header.payload_size),
        )
    observed = crc32_iso_hdlc(payload)
    if observed != header.payload_crc32:
        raise JilProtocolError(
            FRAME_CRC_REJECT,
            "payload CRC mismatch: declared=%#010x observed=%#010x" % (header.payload_crc32, observed),
        )


def build_frame_message(
    *,
    frame_id: int,
    simulation_timestamp_us: int,
    pc_monotonic_us: int,
    width: int,
    height: int,
    payload: bytes,
    channels: int = 3,
    codec: int = int(FrameCodec.JPEG),
    pixel_format: int = int(PixelFormat.BGR8),
    flags: int = 0,
) -> bytes:
    """Build a complete ``header + payload`` frame message."""

    header = FrameHeader(
        frame_id=frame_id,
        simulation_timestamp_us=simulation_timestamp_us,
        pc_monotonic_us=pc_monotonic_us,
        width=width,
        height=height,
        payload_size=len(payload),
        payload_crc32=crc32_iso_hdlc(payload),
        channels=channels,
        codec=codec,
        pixel_format=pixel_format,
        flags=flags,
    )
    return encode_frame_header(header) + payload


# ── JILA ACK/status packet ───────────────────────────────────────────────────


@dataclass(frozen=True)
class AckStatusPacket:
    """Fixed 48-byte little-endian ACK/status packet."""

    acked_sequence: int
    receive_timestamp_us: int
    send_timestamp_us: int
    mcu_state: int
    result_code: int
    accepted: int
    range_shift_state: int
    fault_flags: int = 0
    last_valid_command_age_ms: int = 0
    heartbeat_age_ms: int = 0
    message_type: int = int(AckMessageType.COMMAND_ACK)
    protocol_version: int = JIL_PROTOCOL_VERSION
    crc32: int = 0

    @property
    def classification(self) -> str:
        return classification_for_result_code(self.result_code)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "message_type": self.message_type,
            "acked_sequence": self.acked_sequence,
            "receive_timestamp_us": self.receive_timestamp_us,
            "send_timestamp_us": self.send_timestamp_us,
            "mcu_state": self.mcu_state,
            "result_code": self.result_code,
            "classification": self.classification,
            "accepted": self.accepted,
            "range_shift_state": self.range_shift_state,
            "fault_flags": self.fault_flags,
            "last_valid_command_age_ms": self.last_valid_command_age_ms,
            "heartbeat_age_ms": self.heartbeat_age_ms,
            "crc32": self.crc32,
        }


def encode_ack_packet(packet: AckStatusPacket) -> bytes:
    """Serialise an ACK/status packet and append CRC-32 over bytes 0..43."""

    encoded = ACK_STRUCT.pack(
        ACK_MAGIC,
        packet.protocol_version,
        packet.message_type,
        packet.acked_sequence & 0xFFFFFFFF,
        packet.receive_timestamp_us,
        packet.send_timestamp_us,
        packet.mcu_state & 0xFF,
        packet.result_code & 0xFF,
        packet.accepted & 0xFF,
        packet.range_shift_state & 0xFF,
        packet.fault_flags & 0xFFFFFFFF,
        packet.last_valid_command_age_ms & 0xFFFFFFFF,
        packet.heartbeat_age_ms & 0xFFFFFFFF,
        0,
    )
    checksum = crc32_iso_hdlc(encoded[:ACK_CRC_OFFSET])
    return encoded[:ACK_CRC_OFFSET] + struct.pack("<I", checksum)


def decode_ack_packet(data: bytes, *, verify_crc: bool = True) -> AckStatusPacket:
    """Decode and validate a 48-byte ACK/status packet."""

    if len(data) != ACK_PACKET_SIZE:
        raise JilProtocolError(
            ACK_REJECT, "ack packet must be %d bytes, got %d" % (ACK_PACKET_SIZE, len(data))
        )
    (
        magic,
        protocol_version,
        message_type,
        acked_sequence,
        receive_timestamp_us,
        send_timestamp_us,
        mcu_state,
        result_code,
        accepted,
        range_shift_state,
        fault_flags,
        last_valid_command_age_ms,
        heartbeat_age_ms,
        crc32_value,
    ) = ACK_STRUCT.unpack(data)

    if magic != ACK_MAGIC:
        raise JilProtocolError(ACK_REJECT, "unexpected ack magic %r" % (magic,))
    if protocol_version != JIL_PROTOCOL_VERSION:
        raise JilProtocolError(ACK_REJECT, "unsupported ack protocol version %d" % protocol_version)
    if verify_crc:
        expected = crc32_iso_hdlc(data[:ACK_CRC_OFFSET])
        if crc32_value != expected:
            raise JilProtocolError(
                CRC_REJECT,
                "ack CRC mismatch: packet=%#010x expected=%#010x" % (crc32_value, expected),
            )
    return AckStatusPacket(
        acked_sequence=acked_sequence,
        receive_timestamp_us=receive_timestamp_us,
        send_timestamp_us=send_timestamp_us,
        mcu_state=mcu_state,
        result_code=result_code,
        accepted=accepted,
        range_shift_state=range_shift_state,
        fault_flags=fault_flags,
        last_valid_command_age_ms=last_valid_command_age_ms,
        heartbeat_age_ms=heartbeat_age_ms,
        message_type=message_type,
        protocol_version=protocol_version,
        crc32=crc32_value,
    )


def protocol_descriptor() -> Dict[str, Any]:
    """Machine-readable Phase 13B protocol descriptor for run evidence."""

    return {
        "jil_protocol_version": JIL_PROTOCOL_VERSION,
        "frame_magic": FRAME_MAGIC.decode("ascii"),
        "frame_header_size_bytes": FRAME_HEADER_SIZE,
        "frame_header_struct": FRAME_HEADER_STRUCT.format
        if isinstance(FRAME_HEADER_STRUCT.format, str)
        else FRAME_HEADER_STRUCT.format.decode("ascii"),
        "frame_byte_order": "little_endian",
        "frame_codec": "JPEG",
        "frame_declared_decoded_pixel_format": "BGR8",
        "frame_payload_crc_algorithm": "CRC-32/ISO-HDLC",
        "frame_payload_crc_scope": "encoded_payload_only",
        "frame_default_max_payload_bytes": DEFAULT_MAX_PAYLOAD_BYTES,
        "ack_magic": ACK_MAGIC.decode("ascii"),
        "ack_packet_size_bytes": ACK_PACKET_SIZE,
        "ack_byte_order": "little_endian",
        "ack_crc_algorithm": "CRC-32/ISO-HDLC",
        "ack_crc_coverage_bytes": ACK_CRC_OFFSET,
        "ack_crc_field_offset": ACK_CRC_OFFSET,
        "c_result_code_map": dict(C_RESULT_CODE_TO_CLASSIFICATION),
    }


def frame_age_ms(pc_monotonic_us: int, now_pc_clock_us: int) -> Optional[float]:
    """Frame network age in the PC clock domain, or ``None`` when unusable."""

    if pc_monotonic_us <= 0 or now_pc_clock_us <= 0:
        return None
    delta = now_pc_clock_us - pc_monotonic_us
    if delta < 0:
        return None
    return delta / 1000.0
