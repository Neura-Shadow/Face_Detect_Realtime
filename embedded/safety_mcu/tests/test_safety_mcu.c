#include "protocol_parser.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

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

static void finalize_crc(uint8_t *packet) {
    write_u32_le(&packet[MA_VLNA_CRC_OFFSET], ma_vlna_crc32(packet, MA_VLNA_CRC_OFFSET));
}

static void make_packet(uint8_t *packet,
                        uint32_t sequence,
                        uint64_t issued_us,
                        uint64_t valid_until_us,
                        uint32_t lease_id) {
    memset(packet, 0, MA_VLNA_PACKET_SIZE);
    write_u16_le(&packet[0], MA_VLNA_PROTOCOL_VERSION);
    write_u16_le(&packet[2], MA_VLNA_MESSAGE_COMMAND);
    write_u32_le(&packet[4], sequence);
    write_u64_le(&packet[8], issued_us - 100U);
    write_u64_le(&packet[16], issued_us);
    write_u64_le(&packet[24], valid_until_us);
    write_u32_le(&packet[32], lease_id);
    packet[36] = MA_VLNA_CONTROL_AI_ACTIVE;
    packet[37] = MA_VLNA_RANGE_VALID;
    write_u16_le(&packet[38], 1000U);
    write_u16_le(&packet[40], 5000U);
    write_u16_le(&packet[42], 0U);
    write_u16_le(&packet[44], 30000U);
    finalize_crc(packet);
}

static void reset_ready(safety_mcu_context_t *context,
                        protocol_counters_t *counters,
                        uint32_t lease_id,
                        uint64_t lease_expiry) {
    memset(counters, 0, sizeof(*counters));
    safety_fsm_init(context, 300000U, 3U);
    assert(context->state == SAFETY_STATE_BOOT);
    assert(safety_fsm_complete_boot(context));
    assert(context->state == SAFETY_STATE_STANDBY);
    assert(safety_fsm_arm(context));
    assert(context->state == SAFETY_STATE_READY);
    context->active_lease_id = lease_id;
    context->lease_expires_us = lease_expiry;
}

static void test_transition_matrix(void) {
    static const bool expected[6][6] = {
        {true, true, false, false, false, true},
        {false, true, true, false, false, true},
        {false, false, true, true, true, true},
        {false, false, true, true, true, true},
        {false, false, true, true, true, true},
        {false, true, false, false, false, true}
    };
    int from;
    int to;
    for (from = SAFETY_STATE_BOOT; from <= SAFETY_STATE_FAILSAFE; ++from) {
        for (to = SAFETY_STATE_BOOT; to <= SAFETY_STATE_FAILSAFE; ++to) {
            assert(safety_fsm_can_transition((safety_state_t)from, (safety_state_t)to) ==
                   expected[from][to]);
        }
    }
}

int main(void) {
    safety_mcu_context_t context;
    protocol_counters_t counters;
    uint8_t packet[MA_VLNA_PACKET_SIZE];
    const uint64_t now_us = 1000000U;

    assert(sizeof(ma_vlna_command_packet_t) == MA_VLNA_PACKET_SIZE);
    test_transition_matrix();
    reset_ready(&context, &counters, 77U, now_us + 1000000U);

    make_packet(packet, 10U, now_us, now_us + 500000U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_ACCEPTED);
    assert(context.state == SAFETY_STATE_ACTIVE);
    assert(context.watchdog_kick_allowed);

    packet[12] ^= 0x01U;
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_CRC_REJECT);
    packet[12] ^= 0x01U;

    make_packet(packet, 11U, now_us - 1000U, now_us - 1U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_STALE_REJECT);

    make_packet(packet, 10U, now_us, now_us + 500000U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_SEQUENCE_REJECT);
    make_packet(packet, 9U, now_us, now_us + 500000U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_SEQUENCE_REJECT);

    context.lease_expires_us = now_us - 1U;
    make_packet(packet, 12U, now_us, now_us + 500000U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_LEASE_REJECT);
    context.lease_expires_us = now_us + 1000000U;

    make_packet(packet, 12U, now_us, now_us + 500000U, 77U);
    write_u16_le(&packet[0], MA_VLNA_PROTOCOL_VERSION + 1U);
    finalize_crc(packet);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_VERSION_REJECT);

    make_packet(packet, 12U, now_us, now_us + 500000U, 77U);
    write_u16_le(&packet[40], MA_VLNA_CONTROL_SCALE + 1U);
    finalize_crc(packet);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_RANGE_REJECT);

    make_packet(packet, 12U, now_us, now_us + 500000U, 77U);
    assert(protocol_receive_command(&context, &counters, packet, sizeof(packet), now_us) == PROTOCOL_ACCEPTED);
    safety_fsm_tick(&context, now_us + 300001U);
    assert(context.state == SAFETY_STATE_FAILSAFE);
    assert(!context.watchdog_kick_allowed);
    assert(safety_fsm_clear_failsafe(&context));
    assert(context.state == SAFETY_STATE_STANDBY);

    assert(counters.packets_accepted == 2U);
    assert(counters.crc_reject_count == 1U);
    assert(counters.stale_reject_count == 1U);
    assert(counters.sequence_reject_count == 2U);
    assert(counters.lease_reject_count == 1U);
    assert(counters.version_reject_count == 1U);
    assert(counters.control_range_reject_count == 1U);
    assert(context.failsafe_entry_count == 1U);
    assert(context.failsafe_recovery_count == 1U);

    printf("phase13a portable C protocol/FSM tests passed\n");
    return 0;
}
