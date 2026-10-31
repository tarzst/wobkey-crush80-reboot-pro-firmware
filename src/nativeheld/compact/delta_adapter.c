#include "delta_adapter.h"
#include "rc2_builtin_dictionary.h"

__attribute__((always_inline)) static inline int valid_writer(const ccd_writer *writer)
{
    return writer != NULL && writer->basic != NULL && writer->bitmap != NULL &&
           writer->emit != NULL && writer->overflow_enabled <= 1;
}

static int in_bitmap(const volatile uint8_t *bitmap, unsigned usage)
{
    if (usage < VCK_USAGE_MIN || usage > 0x70) {
        return 0;
    }
    unsigned bit = usage - VCK_USAGE_MIN;
    return (bitmap[1 + bit / 8] & (1u << (bit % 8))) != 0;
}

/* A source can only add/remove its own raw action. Recompute the union after
 * mutation; emit only the action components that actually changed. Thus the
 * OEM's OR/AND-NOT operations never remove another owner's contribution or
 * append a duplicate usage. All failure checks precede the first emission.
 */
static vck_result update(cch_state *state, const ccd_writer *writer,
                          vck_action action, uint8_t down)
{
    vck_action desired;
    vck_result result = cch_query(state, cch_rc2_builtin_dictionary, CCH_RC2_BUILTIN_COUNT,
                                  action.usage, &desired);
    if (result != VCK_OK) {
        return result;
    }
    const volatile uint8_t *basic = writer->basic, *bitmap = writer->bitmap;
    if (basic[1] != 0 || bitmap[0] != 1 || (bitmap[14] & 0xe0u) != 0 || bitmap[15] != 0) {
        return VCK_INVALID;
    }
    unsigned free = 0, present = 0;
    for (unsigned i = 2; i < 8; ++i) {
        unsigned usage = basic[i];
        if (usage == 0) {
            ++free;
            continue;
        }
        if (usage < VCK_USAGE_MIN || (usage > VCK_USAGE_MAX && usage != CCH_OEM_USAGE) ||
            in_bitmap(bitmap, usage)) {
            return VCK_INVALID;
        }
        for (unsigned j = 2; j < i; ++j) {
            if (basic[j] == usage) {
                return VCK_INVALID;
            }
        }
        present |= (unsigned)(usage == action.usage);
    }
    uint8_t old_modifiers = basic[0];
    uint8_t modifiers = (uint8_t)(old_modifiers ^ desired.modifiers);
    /* An inconsistent external report must not turn a press into a release. */
    if ((down && (old_modifiers & modifiers) != 0) ||
        (!down && (desired.modifiers & modifiers) != 0) || (modifiers & (uint8_t)~action.modifiers) != 0) {
        return VCK_INVALID;
    }
    uint8_t usage_delta = 0;
    if (action.usage != 0) {
        int wanted = desired.usage != 0;
        present |= (unsigned)in_bitmap(bitmap, action.usage);
        if (wanted != (present != 0)) {
            if (wanted != down) {
                return VCK_INVALID;
            }
            if (down && free == 0) {
                if (!writer->overflow_enabled) {
                    return VCK_OVERFLOW;
                }
                if (action.usage > 0x70) {
                    return VCK_UNSUPPORTED;
                }
            }
            usage_delta = action.usage;
        }
    }
    if (modifiers != 0 || usage_delta != 0) {
        writer->emit(writer->context, modifiers, usage_delta, down);
    }
    return VCK_OK;
}

vck_result ccd_physical(cch_state *state, const ccd_writer *writer,
                        uint16_t position, uint8_t down, uint16_t code, cch_event *out)
{
    if (state == NULL || !valid_writer(writer) || position >= CCH_POSITIONS || down > 1 || out == NULL) {
        return VCK_INVALID;
    }
    uint8_t before_active = state->active[position / 8];
    uint16_t before_code = state->physical[position];
    cch_event event;
    vck_result result = cch_physical(state, position, down, code, &event);
    if (result == VCK_OK && event.route == CCH_KEYBOARD) {
        vck_action action;
        result = cch_decode(event.code, &action);
        if (result == VCK_OK) {
            result = update(state, writer, action, down);
        }
        if (result != VCK_OK) {
            state->active[position / 8] = before_active;
            state->physical[position] = before_code;
        }
    }
    if (result == VCK_OK) {
        *out = event;
    }
    return result;
}

vck_result ccd_synthetic(cch_state *state, const ccd_writer *writer,
                         uint16_t source, uint8_t down, vck_action action)
{
    if (state == NULL || !valid_writer(writer) || down > 1) {
        return VCK_INVALID;
    }
    uint8_t *owner;
    uint8_t before;
    vck_result result;
    if (source >= VCSYN_BUILTIN_BASE && source < VCSYN_MACRO_MOD_BASE) {
        unsigned position = (unsigned)source - VCSYN_BUILTIN_BASE;
        owner = &state->builtin[position];
        before = *owner;
        if (before > CCH_RC2_BUILTIN_COUNT) {
            return VCK_INVALID;
        }
        if (before != 0) {
            uint16_t packed = cch_rc2_builtin_dictionary[before - 1];
            action = (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed};
        }
        result = cch_builtin(state, (uint16_t)position, down, action,
                             cch_rc2_builtin_dictionary, CCH_RC2_BUILTIN_COUNT);
        if (result != VCK_OK || before == *owner) {
            return result;
        }
    } else if (source >= VCSYN_MACRO_MOD_BASE && source < VCSYN_CAPACITY) {
        unsigned index = (unsigned)source - VCSYN_MACRO_MOD_BASE;
        vck_action expected = index < 8 ? (vck_action){(uint8_t)(1u << index), 0} :
                              (vck_action){0, (uint8_t)(index - 8 + VCK_USAGE_MIN)};
        if (action.modifiers != expected.modifiers || action.usage != expected.usage) {
            return VCK_UNSUPPORTED;
        }
        return ccd_macro_action(state, writer, down, action);
    } else {
        return source == VCSYN_NO_SOURCE && action.modifiers == 0 && action.usage == 0 ?
               VCK_OK : VCK_UNSUPPORTED;
    }
    result = update(state, writer, action, down);
    if (result != VCK_OK) {
        *owner = before;
    }
    return result;
}

vck_result ccd_macro_action(cch_state *state, const ccd_writer *writer,
                            uint8_t down, vck_action action)
{
    if (state == NULL || !valid_writer(writer) || down > 1) {
        return VCK_INVALID;
    }
    if (action.usage != 0 && (action.usage < VCK_USAGE_MIN || action.usage > VCK_USAGE_MAX)) {
        return VCK_UNSUPPORTED;
    }
    unsigned index = action.usage == 0 ? 0 : 1u + ((unsigned)action.usage - VCK_USAGE_MIN) / 8u;
    uint8_t before_modifiers = state->macro[0], before_usage = state->macro[index];
    state->macro[0] = down ? (uint8_t)(before_modifiers | action.modifiers) :
                            (uint8_t)(before_modifiers & (uint8_t)~action.modifiers);
    if (action.usage != 0) {
        uint8_t mask = (uint8_t)(1u << (((unsigned)action.usage - VCK_USAGE_MIN) % 8));
        state->macro[index] = down ? (uint8_t)(before_usage | mask) :
                                    (uint8_t)(before_usage & (uint8_t)~mask);
    }
    vck_result result = update(state, writer, action, down);
    if (result != VCK_OK) {
        state->macro[0] = before_modifiers;
        state->macro[index] = before_usage;
    }
    return result;
}
