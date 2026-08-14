#ifndef MA_VLNA_SAFETY_FSM_H
#define MA_VLNA_SAFETY_FSM_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    SAFETY_STATE_BOOT = 0,
    SAFETY_STATE_STANDBY = 1,
    SAFETY_STATE_READY = 2,
    SAFETY_STATE_ACTIVE = 3,
    SAFETY_STATE_DEGRADED = 4,
    SAFETY_STATE_FAILSAFE = 5
} safety_state_t;

typedef struct {
    safety_state_t state;
    uint32_t active_lease_id;
    uint64_t lease_expires_us;
    uint32_t last_sequence;
    uint64_t last_valid_rx_us;
    uint64_t heartbeat_timeout_us;
    uint32_t consecutive_range_rejects;
    uint32_t range_failsafe_threshold;
    uint32_t failsafe_entry_count;
    uint32_t failsafe_recovery_count;
    uint32_t range_reject_count;
    bool has_sequence;
    bool watchdog_kick_allowed;
} safety_mcu_context_t;

void safety_fsm_init(safety_mcu_context_t *context,
                     uint64_t heartbeat_timeout_us,
                     uint32_t range_failsafe_threshold);
bool safety_fsm_can_transition(safety_state_t from, safety_state_t to);
bool safety_fsm_transition(safety_mcu_context_t *context, safety_state_t target);
bool safety_fsm_complete_boot(safety_mcu_context_t *context);
bool safety_fsm_arm(safety_mcu_context_t *context);
bool safety_fsm_clear_failsafe(safety_mcu_context_t *context);
void safety_fsm_on_command(safety_mcu_context_t *context,
                           bool active_ai_authority,
                           bool range_valid,
                           uint64_t now_us);
void safety_fsm_tick(safety_mcu_context_t *context, uint64_t now_us);

#endif
