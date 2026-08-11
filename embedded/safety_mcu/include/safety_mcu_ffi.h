/*
 * Phase 13B narrow C ABI over the frozen Phase 13A Safety MCU.
 *
 * Phase 13B does NOT introduce a second runtime implementation of the Virtual
 * Safety MCU. The portable C parser (protocol_parser.c) and FSM (safety_fsm.c)
 * remain the single runtime source of truth; this header only exposes them
 * through a stable, fixed-layout C ABI that Python can load with ctypes.
 *
 * Guarantees:
 *   - opaque per-instance handle, no global singleton, multiple instances OK;
 *   - allocation happens only in safety_mcu_create/safety_mcu_destroy, never
 *     while receiving a packet;
 *   - the Phase 13A command layout, protocol version, packet size, CRC
 *     coverage, sequence/lease semantics and FSM semantics are unchanged.
 */
#ifndef MA_VLNA_SAFETY_MCU_FFI_H
#define MA_VLNA_SAFETY_MCU_FFI_H

#include <stddef.h>
#include <stdint.h>

#include "command_protocol.h"

#if defined(_WIN32)
#  if defined(MA_VLNA_SAFETY_MCU_FFI_STATIC)
#    define MA_VLNA_FFI_API
#  elif defined(MA_VLNA_SAFETY_MCU_FFI_BUILD)
#    define MA_VLNA_FFI_API __declspec(dllexport)
#  else
#    define MA_VLNA_FFI_API __declspec(dllimport)
#  endif
#else
#  if defined(MA_VLNA_SAFETY_MCU_FFI_BUILD)
#    define MA_VLNA_FFI_API __attribute__((visibility("default")))
#  else
#    define MA_VLNA_FFI_API
#  endif
#endif

#if defined(__cplusplus)
extern "C" {
#endif

/* Bump only when the exported ABI layout or semantics change. */
#define MA_VLNA_SAFETY_MCU_FFI_ABI_VERSION ((uint32_t)1U)

/* safety_mcu_* status codes (distinct from protocol_result_t). */
typedef enum {
    MA_VLNA_FFI_OK = 0,
    MA_VLNA_FFI_NULL_ARGUMENT = -1,
    MA_VLNA_FFI_INVALID_STATE = -2,
    MA_VLNA_FFI_ALLOCATION_FAILED = -3
} ma_vlna_ffi_status_t;

/* Bit flags reported in safety_mcu_receive_result_t.fault_flags. */
#define MA_VLNA_FAULT_NONE ((uint32_t)0U)
#define MA_VLNA_FAULT_REJECTED ((uint32_t)1U << 0)
#define MA_VLNA_FAULT_CRC ((uint32_t)1U << 1)
#define MA_VLNA_FAULT_SEQUENCE ((uint32_t)1U << 2)
#define MA_VLNA_FAULT_STALE ((uint32_t)1U << 3)
#define MA_VLNA_FAULT_LEASE ((uint32_t)1U << 4)
#define MA_VLNA_FAULT_RANGE ((uint32_t)1U << 5)
#define MA_VLNA_FAULT_LENGTH ((uint32_t)1U << 6)
#define MA_VLNA_FAULT_VERSION ((uint32_t)1U << 7)
#define MA_VLNA_FAULT_STATE ((uint32_t)1U << 8)
#define MA_VLNA_FAULT_DEGRADED ((uint32_t)1U << 9)
#define MA_VLNA_FAULT_FAILSAFE ((uint32_t)1U << 10)
#define MA_VLNA_FAULT_SAFE_STOP ((uint32_t)1U << 11)

/*
 * Fixed-layout decode/authority result. Every field is fixed-width and the
 * padding is explicit (reserved_u16) so the ctypes mirror can assert the same
 * size and offsets on both Windows x86-64 and Jetson aarch64.
 */
typedef struct {
    uint8_t accepted;
    uint8_t mcu_state;
    uint8_t result_code;
    uint8_t range_shift_state;
    uint32_t sequence;
    int16_t steering_q15;
    uint16_t throttle_q15;
    uint16_t brake_q15;
    uint16_t reserved_u16;
    uint32_t fault_flags;
    uint32_t last_valid_command_age_ms;
    uint32_t heartbeat_age_ms;
} safety_mcu_receive_result_t;

/* Cumulative counters mirrored from protocol_counters_t plus FSM counters. */
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
    uint32_t range_reject_count;
    uint32_t failsafe_entry_count;
    uint32_t failsafe_recovery_count;
    uint32_t receive_call_count;
    uint32_t session_count;
} safety_mcu_counters_t;

#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(sizeof(safety_mcu_receive_result_t) == 28U,
               "safety_mcu_receive_result_t must stay 28 bytes");
_Static_assert(offsetof(safety_mcu_receive_result_t, sequence) == 4U,
               "safety_mcu_receive_result_t.sequence must stay at offset 4");
_Static_assert(offsetof(safety_mcu_receive_result_t, steering_q15) == 8U,
               "safety_mcu_receive_result_t.steering_q15 must stay at offset 8");
_Static_assert(offsetof(safety_mcu_receive_result_t, fault_flags) == 16U,
               "safety_mcu_receive_result_t.fault_flags must stay at offset 16");
_Static_assert(sizeof(safety_mcu_counters_t) == 56U,
               "safety_mcu_counters_t must stay 56 bytes");
#endif

typedef struct safety_mcu_handle safety_mcu_handle_t;

/* ── Contract accessors (no instance required) ─────────────────────────── */
MA_VLNA_FFI_API uint32_t safety_mcu_get_abi_version(void);
MA_VLNA_FFI_API uint16_t safety_mcu_get_protocol_version(void);
MA_VLNA_FFI_API uint32_t safety_mcu_get_command_packet_size(void);
MA_VLNA_FFI_API uint32_t safety_mcu_get_crc_coverage_bytes(void);
MA_VLNA_FFI_API uint32_t safety_mcu_get_control_scale(void);
MA_VLNA_FFI_API uint32_t safety_mcu_get_receive_result_size(void);
MA_VLNA_FFI_API uint32_t safety_mcu_get_counters_size(void);
MA_VLNA_FFI_API uint32_t safety_mcu_crc32(const uint8_t *data, size_t length);

/* ── Instance lifecycle ────────────────────────────────────────────────── */
MA_VLNA_FFI_API safety_mcu_handle_t *safety_mcu_create(uint64_t heartbeat_timeout_us,
                                                       uint32_t range_failsafe_threshold);
MA_VLNA_FFI_API void safety_mcu_destroy(safety_mcu_handle_t *handle);
MA_VLNA_FFI_API int32_t safety_mcu_reset(safety_mcu_handle_t *handle,
                                         uint64_t heartbeat_timeout_us,
                                         uint32_t range_failsafe_threshold);

/* ── FSM bring-up and authority ────────────────────────────────────────── */
MA_VLNA_FFI_API int32_t safety_mcu_complete_boot(safety_mcu_handle_t *handle);
MA_VLNA_FFI_API int32_t safety_mcu_arm(safety_mcu_handle_t *handle);
MA_VLNA_FFI_API int32_t safety_mcu_clear_failsafe(safety_mcu_handle_t *handle);
MA_VLNA_FFI_API int32_t safety_mcu_set_lease(safety_mcu_handle_t *handle,
                                             uint32_t lease_id,
                                             uint64_t lease_expires_us);

/*
 * Explicit session reset/bootstrap. A reconnecting Jetson node must call this
 * through the negotiated control channel; without it a restarted node cannot
 * silently rewind the sequence window of the running FSM.
 */
MA_VLNA_FFI_API int32_t safety_mcu_begin_session(safety_mcu_handle_t *handle,
                                                 uint32_t lease_id,
                                                 uint64_t lease_expires_us);

/* ── Runtime ───────────────────────────────────────────────────────────── */
MA_VLNA_FFI_API int32_t safety_mcu_receive_packet(safety_mcu_handle_t *handle,
                                                  const uint8_t *packet,
                                                  size_t packet_size,
                                                  uint64_t now_us,
                                                  safety_mcu_receive_result_t *out_result);
MA_VLNA_FFI_API uint8_t safety_mcu_tick(safety_mcu_handle_t *handle, uint64_t now_us);
MA_VLNA_FFI_API uint8_t safety_mcu_get_state(const safety_mcu_handle_t *handle);
MA_VLNA_FFI_API int32_t safety_mcu_get_counters(const safety_mcu_handle_t *handle,
                                                safety_mcu_counters_t *out_counters);

#if defined(__cplusplus)
}
#endif

#endif /* MA_VLNA_SAFETY_MCU_FFI_H */
