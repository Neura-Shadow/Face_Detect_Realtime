#ifndef MA_VLNA_COMMAND_PROTOCOL_H
#define MA_VLNA_COMMAND_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#define MA_VLNA_PROTOCOL_VERSION ((uint16_t)1U)
#define MA_VLNA_PACKET_SIZE ((size_t)64U)
#define MA_VLNA_CRC_OFFSET ((size_t)60U)
#define MA_VLNA_CONTROL_SCALE ((uint16_t)32767U)
#define MA_VLNA_MAX_RESULT_AGE_MS ((uint32_t)150U)
#define MA_VLNA_PROTOCOL_LITTLE_ENDIAN 1

typedef enum {
    MA_VLNA_MESSAGE_COMMAND = 1,
    MA_VLNA_MESSAGE_HEARTBEAT = 2
} ma_vlna_message_type_t;

typedef enum {
    MA_VLNA_CONTROL_HOLD = 0,
    MA_VLNA_CONTROL_MANUAL = 1,
    MA_VLNA_CONTROL_AI_ACTIVE = 2,
    MA_VLNA_CONTROL_SAFE_STOP = 3
} ma_vlna_control_mode_t;

typedef enum {
    MA_VLNA_RANGE_VALID = 0,
    MA_VLNA_RANGE_INPUT_SHIFT = 1,
    MA_VLNA_RANGE_NORMALIZATION_MISMATCH = 2,
    MA_VLNA_RANGE_COLOR_ORDER_MISMATCH = 3,
    MA_VLNA_RANGE_NAN_OR_INF = 4,
    MA_VLNA_RANGE_ACTIVATION_SHIFT = 5,
    MA_VLNA_RANGE_QUANTIZATION_SATURATION = 6,
    MA_VLNA_RANGE_OUTPUT_INVALID = 7,
    MA_VLNA_RANGE_RECOVERY_PENDING = 8
} ma_vlna_range_shift_state_t;

#if defined(_MSC_VER)
#pragma pack(push, 1)
#define MA_VLNA_PACKED
#else
#define MA_VLNA_PACKED __attribute__((packed))
#endif

typedef struct MA_VLNA_PACKED {
    uint16_t protocol_version;
    uint16_t message_type;
    uint32_t sequence;
    uint64_t source_timestamp_us;
    uint64_t issued_timestamp_us;
    uint64_t valid_until_us;
    uint32_t command_lease_id;
    uint8_t control_mode;
    uint8_t range_shift_state;
    int16_t steering;
    uint16_t throttle;
    uint16_t brake;
    uint16_t ai_confidence;
    uint16_t reserved_u16;
    uint32_t result_age_ms;
    uint32_t flags;
    uint32_t reserved_u32;
    uint32_t crc32;
} ma_vlna_command_packet_t;

#if defined(_MSC_VER)
#pragma pack(pop)
#endif

#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(sizeof(ma_vlna_command_packet_t) == MA_VLNA_PACKET_SIZE,
               "MA-VLNA command packet must remain 64 bytes");
#endif

#endif
