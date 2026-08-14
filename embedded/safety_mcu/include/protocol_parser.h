#ifndef MA_VLNA_PROTOCOL_PARSER_H
#define MA_VLNA_PROTOCOL_PARSER_H

#include <stddef.h>
#include <stdint.h>

#include "command_protocol.h"
#include "safety_fsm.h"

typedef enum {
    PROTOCOL_ACCEPTED = 0,
    PROTOCOL_LENGTH_REJECT = 1,
    PROTOCOL_CRC_REJECT = 2,
    PROTOCOL_STALE_REJECT = 3,
    PROTOCOL_SEQUENCE_REJECT = 4,
    PROTOCOL_LEASE_REJECT = 5,
    PROTOCOL_VERSION_REJECT = 6,
    PROTOCOL_RANGE_REJECT = 7,
    PROTOCOL_STATE_REJECT = 8
} protocol_result_t;

typedef struct {
    uint32_t packets_accepted;
    uint32_t length_reject_count;
    uint32_t crc_reject_count;
    uint32_t stale_reject_count;
    uint32_t sequence_reject_count;
    uint32_t lease_reject_count;
    uint32_t version_reject_count;
    uint32_t control_range_reject_count;
    uint32_t state_reject_count;
} protocol_counters_t;

uint32_t ma_vlna_crc32(const uint8_t *data, size_t length);
protocol_result_t protocol_receive_command(
    safety_mcu_context_t *context,
    protocol_counters_t *counters,
    const uint8_t *rx_buffer,
    size_t rx_length,
    uint64_t now_us);

#endif
