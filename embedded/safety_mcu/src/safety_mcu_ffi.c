/*
 * Phase 13B narrow C ABI implementation.
 *
 * Every acceptance decision is delegated to the unchanged Phase 13A
 * protocol_receive_command()/safety_fsm_*() implementation. This file only
 * owns the opaque instance, the fixed-layout result marshalling and the
 * decode of the already-C-validated control values.
 */
#include "safety_mcu_ffi.h"

#include <stdlib.h>
#include <string.h>

#include "protocol_parser.h"
#include "safety_fsm.h"

struct safety_mcu_handle {
    safety_mcu_context_t context;
    protocol_counters_t counters;
    uint64_t last_valid_command_us;
    uint32_t session_count;
    uint32_t receive_call_count;
};

static uint16_t ffi_read_u16_le(const uint8_t *data) {
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8U));
}

static int16_t ffi_read_i16_le(const uint8_t *data) {
    return (int16_t)ffi_read_u16_le(data);
}

static uint32_t ffi_read_u32_le(const uint8_t *data) {
    return (uint32_t)data[0] | ((uint32_t)data[1] << 8U) |
           ((uint32_t)data[2] << 16U) | ((uint32_t)data[3] << 24U);
}

static uint32_t ffi_age_ms(uint64_t now_us, uint64_t reference_us) {
    uint64_t elapsed;
    if (reference_us == 0U || now_us < reference_us) {
        return 0U;
    }
    elapsed = (now_us - reference_us) / 1000U;
    if (elapsed > (uint64_t)0xFFFFFFFFU) {
        return 0xFFFFFFFFU;
    }
    return (uint32_t)elapsed;
}

static uint32_t ffi_fault_flags(protocol_result_t result, safety_state_t state) {
    uint32_t flags = MA_VLNA_FAULT_NONE;
    switch (result) {
        case PROTOCOL_ACCEPTED: break;
        case PROTOCOL_LENGTH_REJECT: flags |= MA_VLNA_FAULT_LENGTH; break;
        case PROTOCOL_CRC_REJECT: flags |= MA_VLNA_FAULT_CRC; break;
        case PROTOCOL_STALE_REJECT: flags |= MA_VLNA_FAULT_STALE; break;
        case PROTOCOL_SEQUENCE_REJECT: flags |= MA_VLNA_FAULT_SEQUENCE; break;
        case PROTOCOL_LEASE_REJECT: flags |= MA_VLNA_FAULT_LEASE; break;
        case PROTOCOL_VERSION_REJECT: flags |= MA_VLNA_FAULT_VERSION; break;
        case PROTOCOL_RANGE_REJECT: flags |= MA_VLNA_FAULT_RANGE; break;
        case PROTOCOL_STATE_REJECT: flags |= MA_VLNA_FAULT_STATE; break;
        default: break;
    }
    if (result != PROTOCOL_ACCEPTED) {
        flags |= MA_VLNA_FAULT_REJECTED;
    }
    if (state == SAFETY_STATE_DEGRADED) {
        flags |= MA_VLNA_FAULT_DEGRADED;
    }
    if (state == SAFETY_STATE_FAILSAFE) {
        flags |= MA_VLNA_FAULT_FAILSAFE;
    }
    return flags;
}

uint32_t safety_mcu_get_abi_version(void) {
    return MA_VLNA_SAFETY_MCU_FFI_ABI_VERSION;
}

uint16_t safety_mcu_get_protocol_version(void) {
    return MA_VLNA_PROTOCOL_VERSION;
}

uint32_t safety_mcu_get_command_packet_size(void) {
    return (uint32_t)MA_VLNA_PACKET_SIZE;
}

uint32_t safety_mcu_get_crc_coverage_bytes(void) {
    return (uint32_t)MA_VLNA_CRC_OFFSET;
}

uint32_t safety_mcu_get_control_scale(void) {
    return (uint32_t)MA_VLNA_CONTROL_SCALE;
}

uint32_t safety_mcu_get_receive_result_size(void) {
    return (uint32_t)sizeof(safety_mcu_receive_result_t);
}

uint32_t safety_mcu_get_counters_size(void) {
    return (uint32_t)sizeof(safety_mcu_counters_t);
}

uint32_t safety_mcu_crc32(const uint8_t *data, size_t length) {
    if (data == NULL) {
        return 0U;
    }
    return ma_vlna_crc32(data, length);
}

safety_mcu_handle_t *safety_mcu_create(uint64_t heartbeat_timeout_us,
                                       uint32_t range_failsafe_threshold) {
    safety_mcu_handle_t *handle = (safety_mcu_handle_t *)calloc(1U, sizeof(safety_mcu_handle_t));
    if (handle == NULL) {
        return NULL;
    }
    safety_fsm_init(&handle->context, heartbeat_timeout_us, range_failsafe_threshold);
    memset(&handle->counters, 0, sizeof(handle->counters));
    handle->last_valid_command_us = 0U;
    handle->session_count = 0U;
    handle->receive_call_count = 0U;
    return handle;
}

void safety_mcu_destroy(safety_mcu_handle_t *handle) {
    if (handle == NULL) {
        return;
    }
    free(handle);
}

int32_t safety_mcu_reset(safety_mcu_handle_t *handle,
                         uint64_t heartbeat_timeout_us,
                         uint32_t range_failsafe_threshold) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    safety_fsm_init(&handle->context, heartbeat_timeout_us, range_failsafe_threshold);
    memset(&handle->counters, 0, sizeof(handle->counters));
    handle->last_valid_command_us = 0U;
    handle->receive_call_count = 0U;
    return MA_VLNA_FFI_OK;
}

int32_t safety_mcu_complete_boot(safety_mcu_handle_t *handle) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    return safety_fsm_complete_boot(&handle->context) ? MA_VLNA_FFI_OK : MA_VLNA_FFI_INVALID_STATE;
}

int32_t safety_mcu_arm(safety_mcu_handle_t *handle) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    return safety_fsm_arm(&handle->context) ? MA_VLNA_FFI_OK : MA_VLNA_FFI_INVALID_STATE;
}

int32_t safety_mcu_clear_failsafe(safety_mcu_handle_t *handle) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    return safety_fsm_clear_failsafe(&handle->context) ? MA_VLNA_FFI_OK : MA_VLNA_FFI_INVALID_STATE;
}

int32_t safety_mcu_set_lease(safety_mcu_handle_t *handle,
                             uint32_t lease_id,
                             uint64_t lease_expires_us) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    handle->context.active_lease_id = lease_id;
    handle->context.lease_expires_us = lease_expires_us;
    return MA_VLNA_FFI_OK;
}

int32_t safety_mcu_begin_session(safety_mcu_handle_t *handle,
                                 uint32_t lease_id,
                                 uint64_t lease_expires_us) {
    if (handle == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    /* Explicit operator/orchestrator action: a new negotiated session may
     * restart the sequence window. A bare reconnect never reaches this path. */
    handle->context.active_lease_id = lease_id;
    handle->context.lease_expires_us = lease_expires_us;
    handle->context.has_sequence = false;
    handle->context.last_sequence = 0U;
    handle->context.consecutive_range_rejects = 0U;
    handle->last_valid_command_us = 0U;
    handle->session_count++;
    return MA_VLNA_FFI_OK;
}

int32_t safety_mcu_receive_packet(safety_mcu_handle_t *handle,
                                  const uint8_t *packet,
                                  size_t packet_size,
                                  uint64_t now_us,
                                  safety_mcu_receive_result_t *out_result) {
    protocol_result_t result;
    uint16_t message_type;

    if (handle == NULL || out_result == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    memset(out_result, 0, sizeof(*out_result));
    handle->receive_call_count++;

    result = protocol_receive_command(&handle->context,
                                      &handle->counters,
                                      packet,
                                      packet_size,
                                      now_us);

    out_result->result_code = (uint8_t)result;
    out_result->accepted = (uint8_t)((result == PROTOCOL_ACCEPTED) ? 1U : 0U);
    out_result->mcu_state = (uint8_t)handle->context.state;
    out_result->fault_flags = ffi_fault_flags(result, handle->context.state);

    if (result == PROTOCOL_ACCEPTED && packet != NULL && packet_size == MA_VLNA_PACKET_SIZE) {
        message_type = ffi_read_u16_le(&packet[2]);
        out_result->sequence = ffi_read_u32_le(&packet[4]);
        out_result->range_shift_state = packet[37];
        out_result->steering_q15 = ffi_read_i16_le(&packet[38]);
        out_result->throttle_q15 = ffi_read_u16_le(&packet[40]);
        out_result->brake_q15 = ffi_read_u16_le(&packet[42]);
        if (packet[36] == (uint8_t)MA_VLNA_CONTROL_SAFE_STOP) {
            out_result->fault_flags |= MA_VLNA_FAULT_SAFE_STOP;
        }
        if (message_type == (uint16_t)MA_VLNA_MESSAGE_COMMAND) {
            handle->last_valid_command_us = now_us;
        }
    } else if (packet != NULL && packet_size == MA_VLNA_PACKET_SIZE &&
               result != PROTOCOL_CRC_REJECT && result != PROTOCOL_LENGTH_REJECT) {
        /* CRC already validated by the parser, so the sequence field is
         * trustworthy for diagnostics. No control authority is granted. */
        out_result->sequence = ffi_read_u32_le(&packet[4]);
    }

    out_result->last_valid_command_age_ms = ffi_age_ms(now_us, handle->last_valid_command_us);
    out_result->heartbeat_age_ms = ffi_age_ms(now_us, handle->context.last_valid_rx_us);
    return MA_VLNA_FFI_OK;
}

uint8_t safety_mcu_tick(safety_mcu_handle_t *handle, uint64_t now_us) {
    if (handle == NULL) {
        return (uint8_t)SAFETY_STATE_FAILSAFE;
    }
    safety_fsm_tick(&handle->context, now_us);
    return (uint8_t)handle->context.state;
}

uint8_t safety_mcu_get_state(const safety_mcu_handle_t *handle) {
    if (handle == NULL) {
        return (uint8_t)SAFETY_STATE_FAILSAFE;
    }
    return (uint8_t)handle->context.state;
}

int32_t safety_mcu_get_counters(const safety_mcu_handle_t *handle,
                                safety_mcu_counters_t *out_counters) {
    if (handle == NULL || out_counters == NULL) {
        return MA_VLNA_FFI_NULL_ARGUMENT;
    }
    memset(out_counters, 0, sizeof(*out_counters));
    out_counters->packets_accepted = handle->counters.packets_accepted;
    out_counters->length_reject_count = handle->counters.length_reject_count;
    out_counters->crc_reject_count = handle->counters.crc_reject_count;
    out_counters->stale_reject_count = handle->counters.stale_reject_count;
    out_counters->sequence_reject_count = handle->counters.sequence_reject_count;
    out_counters->lease_reject_count = handle->counters.lease_reject_count;
    out_counters->version_reject_count = handle->counters.version_reject_count;
    out_counters->control_range_reject_count = handle->counters.control_range_reject_count;
    out_counters->state_reject_count = handle->counters.state_reject_count;
    out_counters->range_reject_count = handle->context.range_reject_count;
    out_counters->failsafe_entry_count = handle->context.failsafe_entry_count;
    out_counters->failsafe_recovery_count = handle->context.failsafe_recovery_count;
    out_counters->receive_call_count = handle->receive_call_count;
    out_counters->session_count = handle->session_count;
    return MA_VLNA_FFI_OK;
}
