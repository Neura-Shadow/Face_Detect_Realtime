#include "protocol_parser.h"

#include <stdbool.h>
#include <stddef.h>

#define RX_BUFFER_LIMIT ((size_t)64U)

static uint16_t read_u16_le(const uint8_t *data) {
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8U));
}

static int16_t read_i16_le(const uint8_t *data) {
    return (int16_t)read_u16_le(data);
}

static uint32_t read_u32_le(const uint8_t *data) {
    return (uint32_t)data[0] | ((uint32_t)data[1] << 8U) |
           ((uint32_t)data[2] << 16U) | ((uint32_t)data[3] << 24U);
}

static uint64_t read_u64_le(const uint8_t *data) {
    uint64_t value = 0U;
    uint8_t index;
    for (index = 0U; index < 8U; ++index) {
        value |= ((uint64_t)data[index]) << (8U * index);
    }
    return value;
}

uint32_t ma_vlna_crc32(const uint8_t *data, size_t length) {
    uint32_t crc = 0xFFFFFFFFU;
    size_t index;
    uint8_t bit;
    for (index = 0U; index < length; ++index) {
        crc ^= data[index];
        for (bit = 0U; bit < 8U; ++bit) {
            crc = (crc >> 1U) ^ ((crc & 1U) ? 0xEDB88320U : 0U);
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

static protocol_result_t reject(protocol_counters_t *counters,
                                protocol_result_t result) {
    if (counters == NULL) {
        return result;
    }
    switch (result) {
        case PROTOCOL_LENGTH_REJECT: counters->length_reject_count++; break;
        case PROTOCOL_CRC_REJECT: counters->crc_reject_count++; break;
        case PROTOCOL_STALE_REJECT: counters->stale_reject_count++; break;
        case PROTOCOL_SEQUENCE_REJECT: counters->sequence_reject_count++; break;
        case PROTOCOL_LEASE_REJECT: counters->lease_reject_count++; break;
        case PROTOCOL_VERSION_REJECT: counters->version_reject_count++; break;
        case PROTOCOL_RANGE_REJECT: counters->control_range_reject_count++; break;
        case PROTOCOL_STATE_REJECT: counters->state_reject_count++; break;
        default: break;
    }
    return result;
}

protocol_result_t protocol_receive_command(
    safety_mcu_context_t *context,
    protocol_counters_t *counters,
    const uint8_t *rx_buffer,
    size_t rx_length,
    uint64_t now_us) {
    uint16_t protocol_version;
    uint16_t message_type;
    uint32_t sequence;
    uint64_t issued_timestamp_us;
    uint64_t valid_until_us;
    uint32_t command_lease_id;
    uint8_t control_mode;
    uint8_t range_state;
    int16_t steering;
    uint16_t throttle;
    uint16_t brake;
    uint16_t ai_confidence;
    uint16_t reserved_u16;
    uint32_t result_age_ms;
    uint32_t reserved_u32;
    uint32_t packet_crc;
    uint32_t expected_crc;
    bool range_valid;
    bool active_ai;

    if (context == NULL || counters == NULL || rx_buffer == NULL ||
        rx_length != MA_VLNA_PACKET_SIZE || rx_length > RX_BUFFER_LIMIT) {
        return reject(counters, PROTOCOL_LENGTH_REJECT);
    }

    packet_crc = read_u32_le(&rx_buffer[MA_VLNA_CRC_OFFSET]);
    expected_crc = ma_vlna_crc32(rx_buffer, MA_VLNA_CRC_OFFSET);
    if (packet_crc != expected_crc) {
        return reject(counters, PROTOCOL_CRC_REJECT);
    }

    protocol_version = read_u16_le(&rx_buffer[0]);
    message_type = read_u16_le(&rx_buffer[2]);
    sequence = read_u32_le(&rx_buffer[4]);
    issued_timestamp_us = read_u64_le(&rx_buffer[16]);
    valid_until_us = read_u64_le(&rx_buffer[24]);
    command_lease_id = read_u32_le(&rx_buffer[32]);
    control_mode = rx_buffer[36];
    range_state = rx_buffer[37];
    steering = read_i16_le(&rx_buffer[38]);
    throttle = read_u16_le(&rx_buffer[40]);
    brake = read_u16_le(&rx_buffer[42]);
    ai_confidence = read_u16_le(&rx_buffer[44]);
    reserved_u16 = read_u16_le(&rx_buffer[46]);
    result_age_ms = read_u32_le(&rx_buffer[48]);
    reserved_u32 = read_u32_le(&rx_buffer[56]);

    if (protocol_version != MA_VLNA_PROTOCOL_VERSION) {
        return reject(counters, PROTOCOL_VERSION_REJECT);
    }
    if (valid_until_us < now_us || issued_timestamp_us > now_us) {
        return reject(counters, PROTOCOL_STALE_REJECT);
    }
    if (context->has_sequence && sequence <= context->last_sequence) {
        return reject(counters, PROTOCOL_SEQUENCE_REJECT);
    }
    if (command_lease_id != context->active_lease_id || now_us > context->lease_expires_us) {
        return reject(counters, PROTOCOL_LEASE_REJECT);
    }
    if ((message_type != MA_VLNA_MESSAGE_COMMAND && message_type != MA_VLNA_MESSAGE_HEARTBEAT) ||
        control_mode > MA_VLNA_CONTROL_SAFE_STOP ||
        range_state > MA_VLNA_RANGE_RECOVERY_PENDING ||
        steering < -(int32_t)MA_VLNA_CONTROL_SCALE ||
        throttle > MA_VLNA_CONTROL_SCALE || brake > MA_VLNA_CONTROL_SCALE ||
        ai_confidence > MA_VLNA_CONTROL_SCALE ||
        reserved_u16 != 0U || reserved_u32 != 0U ||
        result_age_ms > MA_VLNA_MAX_RESULT_AGE_MS ||
        (control_mode == MA_VLNA_CONTROL_AI_ACTIVE && range_state != MA_VLNA_RANGE_VALID)) {
        return reject(counters, PROTOCOL_RANGE_REJECT);
    }
    if (!(context->state == SAFETY_STATE_READY || context->state == SAFETY_STATE_ACTIVE ||
          context->state == SAFETY_STATE_DEGRADED)) {
        return reject(counters, PROTOCOL_STATE_REJECT);
    }

    context->last_sequence = sequence;
    context->has_sequence = true;
    counters->packets_accepted++;
    range_valid = range_state == MA_VLNA_RANGE_VALID;
    active_ai = control_mode == MA_VLNA_CONTROL_AI_ACTIVE;
    safety_fsm_on_command(context, active_ai, range_valid, now_us);
    return PROTOCOL_ACCEPTED;
}
