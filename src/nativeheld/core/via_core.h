#ifndef CRUSH80_VIA_CORE_H
#define CRUSH80_VIA_CORE_H

#include <stddef.h>
#include <stdint.h>

/* Freestanding behavior core. No stock ABI, addresses, transports or globals.
 * Calls on a state must be serialized by its owner. Storage is caller-owned
 * and must outlive the state. The adapter may inspect holds but must not mutate
 * them. Keymap/order storage must remain stable for the duration of one call.
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

enum { VCK_HOLD_EMPTY = 0, VCK_HOLD_KEYCODE = 1, VCK_HOLD_RAW = 2 };

typedef struct {
    uint16_t code; /* zero for RAW; action is authoritative for that kind */
    uint8_t layer;
    uint8_t kind;
    vck_action action;
} vck_hold;

typedef struct {
    vck_hold *holds;
    uint16_t capacity;
} vck_state;

typedef struct {
    uint16_t code;
    uint8_t layer;
} vck_resolved;

/* Logical bitmap starting at usage 4. This is NOT a USB/BLE HID report. */
typedef struct {
    uint8_t modifiers;
    uint8_t usages[VCK_USAGE_BYTES];
} vck_report;

_Static_assert(sizeof(vck_hold) == 6, "hold layout must be six bytes");
_Static_assert(sizeof(vck_report) == 19, "logical report layout changed");

vck_result vck_init(vck_state *state, vck_hold *storage, uint16_t capacity);
vck_result vck_reset(vck_state *state);
vck_result vck_decode(uint16_t code, vck_action *out);
vck_result vck_resolve_be(const uint8_t *keymap, size_t keymap_bytes,
                          uint16_t position, const uint8_t *order,
                          size_t order_count, vck_resolved *out);
vck_result vck_press_physical(vck_state *state, uint16_t position,
                              const uint8_t *keymap, size_t keymap_bytes,
                              const uint8_t *order, size_t order_count);
/* An adapter can resolve once, then decode/latch that exact result here. */
vck_result vck_press_resolved(vck_state *state, uint16_t position, vck_resolved resolved);
/* Slots 0..127 are physical; remaining slots are adapter-assigned identities
 * for independently releasable macro/builtin holds. Capacity and identity
 * allocation are explicit adapter obligations, not inferred from keycodes.
 */
vck_result vck_press_synthetic(vck_state *state, uint16_t source, uint16_t code);
/* Stock writer ABI: arbitrary left/right modifier mask plus at most one usage.
 * No fake QMK encoding. A repeated occupied source keeps its original action.
 */
vck_result vck_press_synthetic_action(vck_state *state, uint16_t source, vck_action action);
vck_result vck_release(vck_state *state, uint16_t source);
vck_result vck_get_report(const vck_state *state, vck_report *out);

#endif
