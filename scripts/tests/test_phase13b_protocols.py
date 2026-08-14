"""Phase 13B wire-protocol golden-vector tests (JILF frames, JILA ACKs).

These tests pin the Phase 13B frame and ACK layouts and re-assert that the
frozen Phase 13A command contract is untouched.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import unittest
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.embedded_command_bridge import (
    CRC_OFFSET as COMMAND_CRC_OFFSET,
)
from workers.core.embedded_command_bridge import (
    PACKET_SIZE as COMMAND_PACKET_SIZE,
)
from workers.core.embedded_command_bridge import (
    PROTOCOL_VERSION as COMMAND_PROTOCOL_VERSION,
)
from workers.core.frame_transport import (
    FrameStreamClient,
    FrameTransportError,
    JpegCodec,
    jpeg_codec_preflight,
    recv_control_message,
    send_control_message,
)
from workers.core.jil_protocol import (
    ACK_CRC_OFFSET,
    ACK_PACKET_SIZE,
    ACK_STRUCT,
    DEFAULT_MAX_PAYLOAD_BYTES,
    FRAME_HEADER_SIZE,
    FRAME_HEADER_STRUCT,
    FRAME_MAGIC,
    ACK_MAGIC,
    AckStatusPacket,
    FrameCodec,
    FrameHeader,
    JilProtocolError,
    PixelFormat,
    build_frame_message,
    classification_for_result_code,
    crc32_iso_hdlc,
    decode_ack_packet,
    decode_frame_header,
    encode_ack_packet,
    encode_frame_header,
    verify_frame_payload,
)
from workers.core.latest_frame_mailbox import FixedBufferPool
from workers.core.frame_transport import FrameStreamServer

GOLDEN_HEADER = FrameHeader(
    frame_id=0x0102030405060708,
    simulation_timestamp_us=0x1112131415161718,
    pc_monotonic_us=0x2122232425262728,
    width=640,
    height=360,
    payload_size=4096,
    payload_crc32=0xDEADBEEF,
    channels=3,
    codec=int(FrameCodec.JPEG),
    pixel_format=int(PixelFormat.BGR8),
    flags=0x0005,
)

GOLDEN_ACK = AckStatusPacket(
    acked_sequence=0x01020304,
    receive_timestamp_us=0x1112131415161718,
    send_timestamp_us=0x2122232425262728,
    mcu_state=3,
    result_code=0,
    accepted=1,
    range_shift_state=0,
    fault_flags=0x00000010,
    last_valid_command_age_ms=12,
    heartbeat_age_ms=34,
    message_type=1,
)


class TestCrcContract(unittest.TestCase):
    def test_crc32_iso_hdlc_golden_vector(self) -> None:
        # The canonical CRC-32/ISO-HDLC check value for b"123456789".
        self.assertEqual(crc32_iso_hdlc(b"123456789"), 0xCBF43926)
        self.assertEqual(crc32_iso_hdlc(b""), 0)
        self.assertEqual(crc32_iso_hdlc(b"MA-VLNA"), zlib.crc32(b"MA-VLNA") & 0xFFFFFFFF)


class TestPhase13AContractUnchanged(unittest.TestCase):
    def test_command_packet_contract_is_frozen(self) -> None:
        self.assertEqual(COMMAND_PACKET_SIZE, 64)
        self.assertEqual(COMMAND_CRC_OFFSET, 60)
        self.assertEqual(COMMAND_PROTOCOL_VERSION, 1)

    def test_result_code_mapping_is_documented(self) -> None:
        self.assertEqual(classification_for_result_code(0), "ACCEPTED")
        self.assertEqual(classification_for_result_code(1), "LENGTH_REJECT")
        self.assertEqual(classification_for_result_code(2), "CRC_REJECT")
        self.assertEqual(classification_for_result_code(3), "STALE_REJECT")
        self.assertEqual(classification_for_result_code(4), "SEQUENCE_REJECT")
        self.assertEqual(classification_for_result_code(5), "LEASE_REJECT")
        self.assertEqual(classification_for_result_code(6), "VERSION_REJECT")
        self.assertEqual(classification_for_result_code(7), "RANGE_REJECT")
        self.assertEqual(classification_for_result_code(8), "STATE_REJECT")
        self.assertEqual(classification_for_result_code(99), "UNKNOWN_RESULT_CODE")


class TestFrameHeader(unittest.TestCase):
    def test_header_is_exactly_56_bytes(self) -> None:
        self.assertEqual(FRAME_HEADER_SIZE, 56)
        self.assertEqual(struct.calcsize(FRAME_HEADER_STRUCT.format), 56)
        self.assertEqual(len(encode_frame_header(GOLDEN_HEADER)), 56)

    def test_header_field_offsets_are_pinned(self) -> None:
        encoded = encode_frame_header(GOLDEN_HEADER)
        self.assertEqual(encoded[0:4], FRAME_MAGIC)
        self.assertEqual(struct.unpack_from("<H", encoded, 4)[0], 1)
        self.assertEqual(struct.unpack_from("<H", encoded, 6)[0], 0x0005)
        self.assertEqual(struct.unpack_from("<H", encoded, 8)[0], 56)
        self.assertEqual(struct.unpack_from("<H", encoded, 10)[0], int(FrameCodec.JPEG))
        self.assertEqual(struct.unpack_from("<Q", encoded, 12)[0], GOLDEN_HEADER.frame_id)
        self.assertEqual(
            struct.unpack_from("<Q", encoded, 20)[0], GOLDEN_HEADER.simulation_timestamp_us
        )
        self.assertEqual(struct.unpack_from("<Q", encoded, 28)[0], GOLDEN_HEADER.pc_monotonic_us)
        self.assertEqual(struct.unpack_from("<I", encoded, 36)[0], 640)
        self.assertEqual(struct.unpack_from("<I", encoded, 40)[0], 360)
        self.assertEqual(struct.unpack_from("<H", encoded, 44)[0], 3)
        self.assertEqual(struct.unpack_from("<H", encoded, 46)[0], int(PixelFormat.BGR8))
        self.assertEqual(struct.unpack_from("<I", encoded, 48)[0], 4096)
        self.assertEqual(struct.unpack_from("<I", encoded, 52)[0], 0xDEADBEEF)

    def test_header_roundtrip(self) -> None:
        decoded = decode_frame_header(encode_frame_header(GOLDEN_HEADER))
        self.assertEqual(decoded.to_dict(), GOLDEN_HEADER.to_dict())

    def test_header_is_little_endian(self) -> None:
        encoded = encode_frame_header(GOLDEN_HEADER)
        self.assertEqual(encoded[36:40], b"\x80\x02\x00\x00")  # width 640 LE

    def test_wrong_header_size_rejected(self) -> None:
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(encode_frame_header(GOLDEN_HEADER)[:55])
        self.assertEqual(ctx.exception.classification, "FRAME_SIZE_REJECT")

    def test_unsupported_version_rejected(self) -> None:
        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        struct.pack_into("<H", encoded, 4, 2)
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_PROTOCOL_REJECT")

    def test_bad_magic_rejected(self) -> None:
        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        encoded[0:4] = b"XXXX"
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_PROTOCOL_REJECT")

    def test_unsupported_codec_rejected(self) -> None:
        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        struct.pack_into("<H", encoded, 10, 0x7FFF)
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_CODEC_REJECT")

    def test_unsupported_pixel_format_rejected(self) -> None:
        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        struct.pack_into("<H", encoded, 46, 0x7F)
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_PIXEL_FORMAT_REJECT")

    def test_invalid_dimensions_rejected(self) -> None:
        for offset in (36, 40):
            encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
            struct.pack_into("<I", encoded, offset, 0)
            with self.assertRaises(JilProtocolError) as ctx:
                decode_frame_header(bytes(encoded))
            self.assertEqual(ctx.exception.classification, "FRAME_SIZE_REJECT")

    def test_zero_and_oversized_payload_rejected(self) -> None:
        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        struct.pack_into("<I", encoded, 48, 0)
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_SIZE_REJECT")

        encoded = bytearray(encode_frame_header(GOLDEN_HEADER))
        struct.pack_into("<I", encoded, 48, DEFAULT_MAX_PAYLOAD_BYTES + 1)
        with self.assertRaises(JilProtocolError) as ctx:
            decode_frame_header(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "FRAME_SIZE_REJECT")


class TestFramePayloadCrc(unittest.TestCase):
    def test_crc_covers_payload_only(self) -> None:
        payload = bytes(range(256)) * 4
        message = build_frame_message(
            frame_id=7,
            simulation_timestamp_us=100,
            pc_monotonic_us=200,
            width=32,
            height=16,
            payload=payload,
        )
        header = decode_frame_header(message[:FRAME_HEADER_SIZE])
        self.assertEqual(header.payload_crc32, crc32_iso_hdlc(payload))
        self.assertNotEqual(header.payload_crc32, crc32_iso_hdlc(message))
        verify_frame_payload(header, message[FRAME_HEADER_SIZE:])

    def test_one_bit_payload_corruption_rejected(self) -> None:
        payload = bytes(range(256))
        message = build_frame_message(
            frame_id=7,
            simulation_timestamp_us=1,
            pc_monotonic_us=2,
            width=16,
            height=16,
            payload=payload,
        )
        header = decode_frame_header(message[:FRAME_HEADER_SIZE])
        corrupted = bytearray(payload)
        corrupted[128] ^= 0x01
        with self.assertRaises(JilProtocolError) as ctx:
            verify_frame_payload(header, bytes(corrupted))
        self.assertEqual(ctx.exception.classification, "FRAME_CRC_REJECT")

    def test_payload_length_mismatch_rejected(self) -> None:
        payload = b"abcdef"
        message = build_frame_message(
            frame_id=1,
            simulation_timestamp_us=1,
            pc_monotonic_us=2,
            width=4,
            height=4,
            payload=payload,
        )
        header = decode_frame_header(message[:FRAME_HEADER_SIZE])
        with self.assertRaises(JilProtocolError) as ctx:
            verify_frame_payload(header, payload[:-1])
        self.assertEqual(ctx.exception.classification, "FRAME_SIZE_REJECT")


class TestAckPacket(unittest.TestCase):
    def test_ack_is_exactly_48_bytes(self) -> None:
        self.assertEqual(ACK_PACKET_SIZE, 48)
        self.assertEqual(struct.calcsize(ACK_STRUCT.format), 48)
        self.assertEqual(len(encode_ack_packet(GOLDEN_ACK)), 48)

    def test_ack_field_offsets_are_pinned(self) -> None:
        encoded = encode_ack_packet(GOLDEN_ACK)
        self.assertEqual(encoded[0:4], ACK_MAGIC)
        self.assertEqual(struct.unpack_from("<H", encoded, 4)[0], 1)
        self.assertEqual(struct.unpack_from("<H", encoded, 6)[0], 1)
        self.assertEqual(struct.unpack_from("<I", encoded, 8)[0], 0x01020304)
        self.assertEqual(struct.unpack_from("<Q", encoded, 12)[0], GOLDEN_ACK.receive_timestamp_us)
        self.assertEqual(struct.unpack_from("<Q", encoded, 20)[0], GOLDEN_ACK.send_timestamp_us)
        self.assertEqual(encoded[28], 3)
        self.assertEqual(encoded[29], 0)
        self.assertEqual(encoded[30], 1)
        self.assertEqual(encoded[31], 0)
        self.assertEqual(struct.unpack_from("<I", encoded, 32)[0], 0x10)
        self.assertEqual(struct.unpack_from("<I", encoded, 36)[0], 12)
        self.assertEqual(struct.unpack_from("<I", encoded, 40)[0], 34)

    def test_ack_crc_covers_bytes_0_to_43(self) -> None:
        encoded = encode_ack_packet(GOLDEN_ACK)
        self.assertEqual(ACK_CRC_OFFSET, 44)
        expected = crc32_iso_hdlc(encoded[:44])
        self.assertEqual(struct.unpack_from("<I", encoded, 44)[0], expected)

    def test_ack_roundtrip(self) -> None:
        decoded = decode_ack_packet(encode_ack_packet(GOLDEN_ACK))
        self.assertEqual(decoded.acked_sequence, GOLDEN_ACK.acked_sequence)
        self.assertEqual(decoded.mcu_state, GOLDEN_ACK.mcu_state)
        self.assertEqual(decoded.classification, "ACCEPTED")

    def test_ack_one_bit_corruption_rejected(self) -> None:
        encoded = bytearray(encode_ack_packet(GOLDEN_ACK))
        encoded[10] ^= 0x01
        with self.assertRaises(JilProtocolError) as ctx:
            decode_ack_packet(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "CRC_REJECT")

    def test_ack_wrong_size_rejected(self) -> None:
        with self.assertRaises(JilProtocolError) as ctx:
            decode_ack_packet(encode_ack_packet(GOLDEN_ACK)[:47])
        self.assertEqual(ctx.exception.classification, "ACK_REJECT")

    def test_ack_bad_magic_rejected(self) -> None:
        encoded = bytearray(encode_ack_packet(GOLDEN_ACK))
        encoded[0:4] = b"ZZZZ"
        with self.assertRaises(JilProtocolError) as ctx:
            decode_ack_packet(bytes(encoded))
        self.assertEqual(ctx.exception.classification, "ACK_REJECT")


class TestAckReceiverValidation(unittest.TestCase):
    def _receiver(self):
        from workers.core.udp_command_transport import AckUdpReceiver

        return AckUdpReceiver("127.0.0.1", 0, timeout_sec=1.0)

    def test_sequence_mismatch_and_stale_ack_rejected(self) -> None:
        from workers.core.udp_command_transport import UdpTransportError

        receiver = self._receiver()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            accepted = AckStatusPacket(
                acked_sequence=10,
                receive_timestamp_us=1,
                send_timestamp_us=2,
                mcu_state=3,
                result_code=0,
                accepted=1,
                range_shift_state=0,
            )
            sender.sendto(encode_ack_packet(accepted), ("127.0.0.1", receiver.port))
            self.assertEqual(receiver.receive_ack(expected_sequence=10).acked_sequence, 10)

            sender.sendto(encode_ack_packet(accepted), ("127.0.0.1", receiver.port))
            with self.assertRaises(UdpTransportError) as ctx:
                receiver.receive_ack(expected_sequence=11)
            self.assertEqual(ctx.exception.classification, "SEQUENCE_REJECT")

            from dataclasses import replace

            stale = replace(accepted, acked_sequence=2)
            sender.sendto(encode_ack_packet(stale), ("127.0.0.1", receiver.port))
            with self.assertRaises(UdpTransportError) as ctx:
                receiver.receive_ack()
            self.assertEqual(ctx.exception.classification, "STALE_REJECT")
        finally:
            sender.close()
            receiver.close()

    def test_rejected_ack_with_sequence_zero_is_not_stale(self) -> None:
        receiver = self._receiver()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            accepted = AckStatusPacket(
                acked_sequence=25,
                receive_timestamp_us=1,
                send_timestamp_us=2,
                mcu_state=3,
                result_code=0,
                accepted=1,
                range_shift_state=0,
            )
            sender.sendto(encode_ack_packet(accepted), ("127.0.0.1", receiver.port))
            receiver.receive_ack()
            crc_reject = AckStatusPacket(
                acked_sequence=0,
                receive_timestamp_us=3,
                send_timestamp_us=4,
                mcu_state=3,
                result_code=2,
                accepted=0,
                range_shift_state=0,
            )
            sender.sendto(encode_ack_packet(crc_reject), ("127.0.0.1", receiver.port))
            observed = receiver.receive_ack()
            self.assertEqual(observed.classification, "CRC_REJECT")
        finally:
            sender.close()
            receiver.close()


class TestFrameTransportOverTcp(unittest.TestCase):
    """Partial-read, oversize and reconnect behaviour over a real TCP socket."""

    def setUp(self) -> None:
        self.pool = FixedBufferPool(size=3, capacity_bytes=1 << 20)
        self.server = FrameStreamServer(
            "127.0.0.1", 0, pool=self.pool, timeout_sec=5.0, max_payload_bytes=1 << 20
        )
        self.port = self.server.bind()

    def tearDown(self) -> None:
        self.server.close()

    def _accept_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=lambda: self.server.accept(timeout_sec=5.0))
        thread.start()
        return thread

    def test_frame_roundtrip_and_partial_write_handling(self) -> None:
        thread = self._accept_in_background()
        client = FrameStreamClient("127.0.0.1", self.port, timeout_sec=5.0)
        client.connect()
        thread.join(timeout=5)

        payload = bytes(range(256)) * 512  # 128 KiB, forces multiple TCP segments
        message = build_frame_message(
            frame_id=42,
            simulation_timestamp_us=1234,
            pc_monotonic_us=5678,
            width=64,
            height=64,
            payload=payload,
        )
        client.send_frame_message(message)
        header, buffer = self.server.receive_frame(timeout_sec=5.0)
        try:
            self.assertEqual(header.frame_id, 42)
            self.assertEqual(header.payload_size, len(payload))
            self.assertEqual(buffer.payload(), payload)
        finally:
            self.pool.release(buffer)
        client.close()

    def test_partial_payload_then_disconnect_is_a_transport_error(self) -> None:
        thread = self._accept_in_background()
        client = FrameStreamClient("127.0.0.1", self.port, timeout_sec=5.0)
        client.connect()
        thread.join(timeout=5)

        payload = b"\x5a" * 4096
        message = build_frame_message(
            frame_id=1,
            simulation_timestamp_us=1,
            pc_monotonic_us=2,
            width=16,
            height=16,
            payload=payload,
        )
        client.send_raw(message[: FRAME_HEADER_SIZE + 100])
        client.close()
        with self.assertRaises(FrameTransportError):
            self.server.receive_frame(timeout_sec=3.0)
        # The bounded pool must not leak after a mid-payload disconnect.
        self.assertFalse(self.pool.leak_check()["buffer_leak_detected"])

    def test_control_channel_json_roundtrip(self) -> None:
        left, right = socket.socketpair()
        try:
            send_control_message(left, {"command": "hello", "value": 13})
            message = recv_control_message(right, timeout_sec=2.0)
            self.assertEqual(message["command"], "hello")
            self.assertEqual(message["value"], 13)
        finally:
            left.close()
            right.close()


class TestJpegCodecContract(unittest.TestCase):
    def test_jpeg_preflight_and_bgra_conversion(self) -> None:
        import numpy as np

        report = jpeg_codec_preflight()
        self.assertTrue(report["jpeg_codec_available"], report)
        self.assertTrue(report["jpeg_roundtrip_passed"], report)
        self.assertFalse(report["jpeg_auto_install_performed"])

        codec = JpegCodec()
        bgra = np.zeros((8, 8, 4), dtype=np.uint8)
        bgra[:, :, 0] = 10
        bgra[:, :, 1] = 20
        bgra[:, :, 2] = 30
        bgra[:, :, 3] = 255
        bgr = codec.bgra_to_bgr(bgra)
        self.assertEqual(bgr.shape, (8, 8, 3))
        self.assertEqual(int(bgr[0, 0, 0]), 10)
        self.assertEqual(int(bgr[0, 0, 2]), 30)

    def test_encoded_payload_crc_is_stable_for_identical_pixels(self) -> None:
        import numpy as np

        codec = JpegCodec(quality=90)
        frame = np.full((16, 16, 3), 128, dtype=np.uint8)
        first = codec.encode_bgr(frame)
        second = codec.encode_bgr(frame.copy())
        self.assertEqual(crc32_iso_hdlc(first), crc32_iso_hdlc(second))
        decoded = codec.decode_to_bgr(first)
        self.assertEqual(decoded.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
