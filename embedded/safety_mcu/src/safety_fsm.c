#include "safety_fsm.h"

#include <stddef.h>
#include <string.h>

void safety_fsm_init(safety_mcu_context_t *context,
                     uint64_t heartbeat_timeout_us,
                     uint32_t range_failsafe_threshold) {
    if (context == NULL) {
        return;
    }
    memset(context, 0, sizeof(*context));
    context->state = SAFETY_STATE_BOOT;
    context->heartbeat_timeout_us = heartbeat_timeout_us;
    context->range_failsafe_threshold = range_failsafe_threshold;
}

bool safety_fsm_can_transition(safety_state_t from, safety_state_t to) {
    if (from == to) {
        return true;
    }
    switch (from) {
        case SAFETY_STATE_BOOT:
            return to == SAFETY_STATE_STANDBY || to == SAFETY_STATE_FAILSAFE;
        case SAFETY_STATE_STANDBY:
            return to == SAFETY_STATE_READY || to == SAFETY_STATE_FAILSAFE;
        case SAFETY_STATE_READY:
            return to == SAFETY_STATE_ACTIVE || to == SAFETY_STATE_DEGRADED ||
                   to == SAFETY_STATE_FAILSAFE;
        case SAFETY_STATE_ACTIVE:
            return to == SAFETY_STATE_READY || to == SAFETY_STATE_DEGRADED ||
                   to == SAFETY_STATE_FAILSAFE;
        case SAFETY_STATE_DEGRADED:
            return to == SAFETY_STATE_READY || to == SAFETY_STATE_ACTIVE ||
                   to == SAFETY_STATE_FAILSAFE;
        case SAFETY_STATE_FAILSAFE:
            return to == SAFETY_STATE_STANDBY;
        default:
            return false;
    }
}

bool safety_fsm_transition(safety_mcu_context_t *context, safety_state_t target) {
    if (context == NULL || !safety_fsm_can_transition(context->state, target)) {
        return false;
    }
    if (target == SAFETY_STATE_FAILSAFE && context->state != SAFETY_STATE_FAILSAFE) {
        context->failsafe_entry_count++;
    }
    context->state = target;
    context->watchdog_kick_allowed =
        target == SAFETY_STATE_READY || target == SAFETY_STATE_ACTIVE ||
        target == SAFETY_STATE_DEGRADED;
    return true;
}

bool safety_fsm_complete_boot(safety_mcu_context_t *context) {
    return safety_fsm_transition(context, SAFETY_STATE_STANDBY);
}

bool safety_fsm_arm(safety_mcu_context_t *context) {
    return safety_fsm_transition(context, SAFETY_STATE_READY);
}

bool safety_fsm_clear_failsafe(safety_mcu_context_t *context) {
    if (context == NULL || context->state != SAFETY_STATE_FAILSAFE) {
        return false;
    }
    if (!safety_fsm_transition(context, SAFETY_STATE_STANDBY)) {
        return false;
    }
    context->failsafe_recovery_count++;
    context->has_sequence = false;
    context->consecutive_range_rejects = 0U;
    return true;
}

void safety_fsm_on_command(safety_mcu_context_t *context,
                           bool active_ai_authority,
                           bool range_valid,
                           uint64_t now_us) {
    safety_state_t target;
    if (context == NULL) {
        return;
    }
    context->last_valid_rx_us = now_us;
    if (active_ai_authority && range_valid) {
        context->consecutive_range_rejects = 0U;
        (void)safety_fsm_transition(context, SAFETY_STATE_ACTIVE);
        return;
    }
    if (!range_valid) {
        context->range_reject_count++;
        context->consecutive_range_rejects++;
        target = context->consecutive_range_rejects >= context->range_failsafe_threshold
                     ? SAFETY_STATE_FAILSAFE
                     : SAFETY_STATE_DEGRADED;
        (void)safety_fsm_transition(context, target);
        return;
    }
    context->consecutive_range_rejects = 0U;
    (void)safety_fsm_transition(context, SAFETY_STATE_DEGRADED);
}

void safety_fsm_tick(safety_mcu_context_t *context, uint64_t now_us) {
    uint64_t elapsed;
    if (context == NULL ||
        !(context->state == SAFETY_STATE_READY || context->state == SAFETY_STATE_ACTIVE ||
          context->state == SAFETY_STATE_DEGRADED)) {
        return;
    }
    if (context->last_valid_rx_us == 0U || now_us < context->last_valid_rx_us) {
        (void)safety_fsm_transition(context, SAFETY_STATE_FAILSAFE);
        return;
    }
    elapsed = now_us - context->last_valid_rx_us;
    if (elapsed > context->heartbeat_timeout_us) {
        (void)safety_fsm_transition(context, SAFETY_STATE_FAILSAFE);
    }
}
