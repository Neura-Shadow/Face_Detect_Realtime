/*
 * Phase 13B FFI ABI tests.
 *
 * These tests assert the exported ABI contract that the Python ctypes mirror
 * depends on, and prove that the FFI wrapper delegates every acceptance
 * decision to the unchanged Phase 13A parser/FSM.
 */
#include "safety_mcu_ffi.h"

#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "protocol_parser.h"

static void write_u16_le(uint8_t *data, uint16_t value) {
    data[0] = (uint8_t)(value & 0xFFU);
    data[1] = (uint8_t)((value >> 8U) & 0xFFU);
}

static void write_u32_le(uint8_t *data, uint32_t value) {
    uint8_t index;
    for (index = 0U; index < 4U; ++index) {
        data[index] = (uint8_t)((value >> (8U * index)) & 0xFFU);
    }
}

static void write_u64_le(uint8_t *data, uint64_t value) {
    uint8_t index;
    for (index = 0U; index < 8U; ++index) {
        data[index] = (uint8_t)((value >> (8U * index)) & 0xFFU);
    }
}

static void make_packet(uint8_t *packet,
                        uint32_t sequence,
                        uint64_t issued_us,
                        uint64_t valid_until_us,
                        uint32_t lease_id,
                        uint8_t control_mode,
                        uint8_t range_state) {
    memset(packet, 0, MA_VLNA_PACKET_SIZE);
    write_u16_le(&packet[0], MA_VLNA_PROTOCOL_VERSION);
    write_u16_le(&packet[2], MA_VLNA_MESSAGE_COMMAND);
    write_u32_le(&packet[4], sequence);
    write_u64_le(&packet[8], issued_us - 100U);
    write_u64_le(&packet[16], issued_us);
    write_u64_le(&packet[24], valid_until_us);
    write_u32_le(&packet[32], lease_id);
    packet[36] = control_mode;
    packet[37] = range_state;
    write_u16_le(&packet[38], (uint16_t)(int16_t)-1200);
    write_u16_le(&packet[40], 6553U);
    write_u16_le(&packet[42], 0U);
    write_u16_le(&packet[44], 30000U);
    write_u32_le(&packet[MA_VLNA_CRC_OFFSET], ma_vlna_crc32(packet, MA_VLNA_CRC_OFFSET));
}

static void test_abi_contract(void) {
    assert(safety_mcu_get_abi_version() == MA_VLNA_SAFETY_MCU_FFI_ABI_VERSION);
    assert(safety_mcu_get_protocol_version() == MA_VLNA_PROTOCOL_VERSION);
    assert(safety_mcu_get_command_packet_size() == (uint32_t)MA_VLNA_PACKET_SIZE);
    assert(safety_mcu_get_command_packet_size() == 64U);
    assert(safety_mcu_get_crc_coverage_bytes() == 60U);
    assert(safety_mcu_get_control_scale() == 32767U);
    assert(safety_mcu_get_receive_result_size() == 28U);
    assert(safety_mcu_get_counters_size() == 56U);
    assert(sizeof(safety_mcu_receive_result_t) == 28U);
    assert(offsetof(safety_mcu_receive_result_t, accepted) == 0U);
    assert(offsetof(safety_mcu_receive_result_t, mcu_state) == 1U);
    assert(offsetof(safety_mcu_receive_result_t, result_code) == 2U);
    assert(offsetof(safety_mcu_receive_result_t, range_shift_state) == 3U);
    assert(offsetof(safety_mcu_receive_result_t, sequence) == 4U);
    assert(offsetof(safety_mcu_receive_result_t, steering_q15) == 8U);
    assert(offsetof(safety_mcu_receive_result_t, throttle_q15) == 10U);
    assert(offsetof(safety_mcu_receive_result_t, brake_q15) == 12U);
    assert(offsetof(safety_mcu_receive_result_t, fault_flags) == 16U);
    assert(offsetof(safety_mcu_receive_result_t, last_valid_command_age_ms) == 20U);
    assert(offsetof(safety_mcu_receive_result_t, heartbeat_age_ms) == 24U);
}

static void test_null_safety(void) {
    safety_mcu_receive_result_t result;
    assert(safety_mcu_receive_packet(NULL, NULL, 0U, 0U, &result) == MA_VLNA_FFI_NULL_ARGUMENT);
    assert(safety_mcu_complete_boot(NULL) == MA_VLNA_FFI_NULL_ARGUMENT);
    assert(safety_mcu_arm(NULL) == MA_VLNA_FFI_NULL_ARGUMENT);
    assert(safety_mcu_set_lease(NULL, 1U, 1U) == MA_VLNA_FFI_NULL_ARGUMENT);
    assert(safety_mcu_get_counters(NULL, NULL) == MA_VLNA_FFI_NULL_ARGUMENT);
    assert(safety_mcu_get_state(NULL) == (uint8_t)SAFETY_STATE_FAILSAFE);
    safety_mcu_destroy(NULL);
}

static void test_accept_and_reject_paths(void) {
    uint8_t packet[MA_VLNA_PACKET_SIZE];
    safety_mcu_receive_result_t result;
    safety_mcu_counters_t counters;
    safety_mcu_handle_t *handle = safety_mcu_create(300000U, 3U);
    const uint64_t now_us = 1000000U;

    assert(handle != NULL);
    assert(safety_mcu_get_state(handle) == (uint8_t)SAFETY_STATE_BOOT);
    assert(safety_mcu_complete_boot(handle) == MA_VLNA_FFI_OK);
    assert(safety_mcu_arm(handle) == MA_VLNA_FFI_OK);
    assert(safety_mcu_begin_session(handle, 0x13B0U, now_us + 10000000U) == MA_VLNA_FFI_OK);

    make_packet(packet, 1U, now_us, now_us + 500000U, 0x13B0U,
                (uint8_t)MA_VLNA_CONTROL_AI_ACTIVE, (uint8_t)MA_VLNA_RANGE_VALID);
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.accepted == 1U);
    assert(result.result_code == (uint8_t)PROTOCOL_ACCEPTED);
    assert(result.mcu_state == (uint8_t)SAFETY_STATE_ACTIVE);
    assert(result.sequence == 1U);
    assert(result.steering_q15 == (int16_t)-1200);
    assert(result.throttle_q15 == 6553U);
    assert(result.brake_q15 == 0U);
    assert(result.range_shift_state == (uint8_t)MA_VLNA_RANGE_VALID);
    assert(result.fault_flags == MA_VLNA_FAULT_NONE);

    /* CRC corruption must reject and must not expose control values. */
    packet[12] ^= 0x01U;
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.accepted == 0U);
    assert(result.result_code == (uint8_t)PROTOCOL_CRC_REJECT);
    assert(result.throttle_q15 == 0U);
    assert((result.fault_flags & MA_VLNA_FAULT_CRC) != 0U);
    assert((result.fault_flags & MA_VLNA_FAULT_REJECTED) != 0U);

    /* Duplicate sequence must reject. */
    make_packet(packet, 1U, now_us, now_us + 500000U, 0x13B0U,
                (uint8_t)MA_VLNA_CONTROL_AI_ACTIVE, (uint8_t)MA_VLNA_RANGE_VALID);
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.result_code == (uint8_t)PROTOCOL_SEQUENCE_REJECT);
    assert(result.sequence == 1U);
    assert(result.throttle_q15 == 0U);

    /* Wrong lease must reject. */
    make_packet(packet, 2U, now_us, now_us + 500000U, 0xDEADU,
                (uint8_t)MA_VLNA_CONTROL_AI_ACTIVE, (uint8_t)MA_VLNA_RANGE_VALID);
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.result_code == (uint8_t)PROTOCOL_LEASE_REJECT);

    /* Stale command must reject. */
    make_packet(packet, 3U, now_us - 200000U, now_us - 1U, 0x13B0U,
                (uint8_t)MA_VLNA_CONTROL_AI_ACTIVE, (uint8_t)MA_VLNA_RANGE_VALID);
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.result_code == (uint8_t)PROTOCOL_STALE_REJECT);

    /* Wrong datagram size must reject as a length error. */
    assert(safety_mcu_receive_packet(handle, packet, 32U, now_us, &result) == MA_VLNA_FFI_OK);
    assert(result.result_code == (uint8_t)PROTOCOL_LENGTH_REJECT);

    /* SAFE_STOP is accepted and flagged. */
    make_packet(packet, 4U, now_us, now_us + 500000U, 0x13B0U,
                (uint8_t)MA_VLNA_CONTROL_SAFE_STOP, (uint8_t)MA_VLNA_RANGE_NAN_OR_INF);
    assert(safety_mcu_receive_packet(handle, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.accepted == 1U);
    assert((result.fault_flags & MA_VLNA_FAULT_SAFE_STOP) != 0U);
    assert(result.mcu_state == (uint8_t)SAFETY_STATE_DEGRADED);

    /* Heartbeat loss drives FAILSAFE through the unchanged FSM tick. */
    assert(safety_mcu_tick(handle, now_us + 300001U) == (uint8_t)SAFETY_STATE_FAILSAFE);
    assert(safety_mcu_clear_failsafe(handle) == MA_VLNA_FFI_OK);
    assert(safety_mcu_get_state(handle) == (uint8_t)SAFETY_STATE_STANDBY);

    assert(safety_mcu_get_counters(handle, &counters) == MA_VLNA_FFI_OK);
    assert(counters.packets_accepted == 2U);
    assert(counters.crc_reject_count == 1U);
    assert(counters.sequence_reject_count == 1U);
    assert(counters.lease_reject_count == 1U);
    assert(counters.stale_reject_count == 1U);
    assert(counters.length_reject_count == 1U);
    assert(counters.failsafe_entry_count == 1U);
    assert(counters.failsafe_recovery_count == 1U);
    assert(counters.receive_call_count == 7U);
    assert(counters.session_count == 1U);

    safety_mcu_destroy(handle);
}

static void test_multiple_instances_are_independent(void) {
    uint8_t packet[MA_VLNA_PACKET_SIZE];
    safety_mcu_receive_result_t result;
    safety_mcu_counters_t counters_a;
    safety_mcu_counters_t counters_b;
    safety_mcu_handle_t *first = safety_mcu_create(300000U, 3U);
    safety_mcu_handle_t *second = safety_mcu_create(300000U, 3U);
    const uint64_t now_us = 2000000U;

    assert(first != NULL && second != NULL && first != second);
    assert(safety_mcu_complete_boot(first) == MA_VLNA_FFI_OK);
    assert(safety_mcu_arm(first) == MA_VLNA_FFI_OK);
    assert(safety_mcu_begin_session(first, 0x11U, now_us + 1000000U) == MA_VLNA_FFI_OK);

    make_packet(packet, 9U, now_us, now_us + 500000U, 0x11U,
                (uint8_t)MA_VLNA_CONTROL_AI_ACTIVE, (uint8_t)MA_VLNA_RANGE_VALID);
    assert(safety_mcu_receive_packet(first, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.accepted == 1U);

    /* The second instance is still in BOOT and must reject the same packet. */
    assert(safety_mcu_receive_packet(second, packet, sizeof(packet), now_us, &result) ==
           MA_VLNA_FFI_OK);
    assert(result.accepted == 0U);
    assert(result.result_code == (uint8_t)PROTOCOL_LEASE_REJECT);

    assert(safety_mcu_get_counters(first, &counters_a) == MA_VLNA_FFI_OK);
    assert(safety_mcu_get_counters(second, &counters_b) == MA_VLNA_FFI_OK);
    assert(counters_a.packets_accepted == 1U);
    assert(counters_b.packets_accepted == 0U);

    safety_mcu_destroy(first);
    safety_mcu_destroy(second);
}

static void test_crc_helper_matches_parser(void) {
    const uint8_t sample[5] = {0x01U, 0x02U, 0x03U, 0x04U, 0x05U};
    assert(safety_mcu_crc32(sample, sizeof(sample)) == ma_vlna_crc32(sample, sizeof(sample)));
    assert(safety_mcu_crc32(NULL, 0U) == 0U);
}

int main(void) {
    test_abi_contract();
    test_null_safety();
    test_accept_and_reject_paths();
    test_multiple_instances_are_independent();
    test_crc_helper_matches_parser();
    printf("phase13b safety mcu ffi tests passed\n");
    return 0;
}
