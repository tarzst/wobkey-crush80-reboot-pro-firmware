#ifndef CRUSH80_VIA_CORE_H
#define CRUSH80_VIA_CORE_H

#include <stddef.h>
#include <stdint.h>

/* Freestanding behavior core types and constants.
 * No stock ABI, addresses, transports or globals.
 */
enum {
    VCK_POSITIONS = 128,
    VCK_LAYERS = 4,
    VCK_KEYMAP_BYTES = VCK_POSITIONS * VCK_LAYERS * 2,
    VCK_USAGE_MIN = 4,
    VCK_USAGE_MAX = 0x91,
    VCK_USAGE_BYTES = (VCK_USAGE_MAX - VCK_USAGE_MIN + 8) / 8,
    VCK_NO_LAYER = 255
};

enum {
    VCSYN_BUILTIN_BASE = VCK_POSITIONS,
    VCSYN_MACRO_MOD_BASE = VCK_POSITIONS * 2,
    VCSYN_MACRO_USAGE_BASE = VCSYN_MACRO_MOD_BASE + 8,
    VCSYN_CAPACITY = VCSYN_MACRO_USAGE_BASE + VCK_USAGE_MAX - VCK_USAGE_MIN + 1,
    VCSYN_NO_SOURCE = 65535
};

typedef enum {
    VCK_OK = 0,
    VCK_INVALID = 1,
    VCK_UNSUPPORTED = 2,
    VCK_OVERFLOW = 3
} vck_result;

typedef struct {
    uint8_t modifiers;
    uint8_t usage; /* zero means no keyboard usage */
} vck_action;

/* Logical bitmap starting at usage 4. This is NOT a USB/BLE HID report. */
typedef struct {
    uint8_t modifiers;
    uint8_t usages[VCK_USAGE_BYTES];
} vck_report;

_Static_assert(sizeof(vck_report) == 19, "logical report layout changed");

void cdb_memzero(volatile void *ptr, unsigned len);

#endif
