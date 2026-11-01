#ifndef CRUSH80_COMPACT_HOLDS_H
#define CRUSH80_COMPACT_HOLDS_H

#include "../core/via_core.h"

enum {
    CCH_POSITIONS = 128,
    CCH_ACTIVE_BYTES = 16,
    CCH_MACRO_BITS = 8 + VCK_USAGE_MAX - VCK_USAGE_MIN + 1,
    CCH_MACRO_BYTES = (CCH_MACRO_BITS + 7) / 8,
    CCH_NONE = 0,
    CCH_KEYBOARD = 1,
    CCH_STOCK = 2
};

/* OEM's existing magic keycode is a raw basic-report usage, not a VIA
 * modifier encoding. It is outside the legacy logical bitmap's domain. */
enum { CCH_OEM_KEYCODE = 0xeeee, CCH_OEM_USAGE = 0xee };

/* Fixed identities, no allocation/eviction: all 128 physical positions,
 * 128 independent OEM builtin contributors and 150 macro modifier/usages.
 * The selected physical code is authoritative until release. Raw builtin
 * actions use an immutable dictionary: zero means inactive; 1..count are
 * dictionary indices. This is lossless only for actions in that dictionary.
 * An unknown action is rejected without changing any owner.
 */
typedef struct {
    uint16_t physical[CCH_POSITIONS];
    uint8_t active[CCH_ACTIVE_BYTES];
    uint8_t builtin[CCH_POSITIONS];
    uint8_t macro[CCH_MACRO_BYTES];
} cch_state;

_Static_assert(sizeof(cch_state) == 420, "compact state layout changed");
_Static_assert(offsetof(cch_state, active) == 256 &&
               offsetof(cch_state, builtin) == 272 &&
               offsetof(cch_state, macro) == 400, "compact owner arrays must be contiguous");

typedef struct {
    uint16_t code;
    uint8_t route;
} cch_event;

/* Caller owns, initializes and serializes this state. No fixed keyboard RAM,
 * implicit lazy init, heap, global state, writes to flash or report transport.
 * dict entries pack raw modifier mask in bits15..8, usage in bits7..0.
 * Keep the same immutable dictionary while any builtin owner is active.
 * Pointers must not alias state or outputs. IRQ/producer/reset integration
 * and the lifetime of dictionary and storage are caller obligations.
 */
vck_result cch_decode(uint16_t code, vck_action *out);
int cch_keyboard(uint16_t code, vck_action *action);
vck_result cch_reset(cch_state *state, uint8_t preserve_stock);
vck_result cch_builtin(cch_state *state, uint16_t position, uint8_t down,
                        vck_action action, const uint16_t *dict, uint8_t count);
vck_result cch_query(const cch_state *state, const uint16_t *dict, uint8_t count,
                      uint8_t usage, vck_action *out);

#endif
