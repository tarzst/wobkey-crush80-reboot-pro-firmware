#include "delta_adapter.h"
#include "rc2_builtin_dictionary.h"

__attribute__((always_inline)) static inline int valid_writer(const ccd_writer *writer)
{
    return writer != NULL;
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
 * append a duplicate usage.
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
    unsigned free = 0, present = 0;
    for (unsigned i = 2; i < 8; ++i) {
        unsigned usage = basic[i];
        if (usage == 0) {
            ++free;
        } else if (usage == action.usage) {
            present = 1;
        }
    }
    uint8_t modifiers = (uint8_t)(basic[0] ^ desired.modifiers);
    uint8_t usage_delta = 0;
    if (action.usage != 0) {
        present |= (unsigned)in_bitmap(bitmap, action.usage);
        if ((desired.usage != 0) != (present != 0)) {
            if (down && free == 0) {
                if (writer->overflow_enabled == NULL || !*writer->overflow_enabled) {
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
    uint8_t mask = (uint8_t)(1u << (position % 8));
    uint8_t before_active = state->active[position / 8];
    if (((before_active & mask) != 0) == (down != 0)) {
        *out = (cch_event){0, CCH_NONE};
        return VCK_OK;
    }
    uint16_t before_code = state->physical[position];
    uint16_t target_code = down ? code : before_code;
    vck_action action;
    int handled = cch_keyboard(target_code, &action);
    if (down && !handled && target_code >= 0x100 && target_code <= 0x1fff) {
        return VCK_UNSUPPORTED;
    }
    state->physical[position] = down ? target_code : 0;
    state->active[position / 8] = down ? (uint8_t)(before_active | mask) :
                                         (uint8_t)(before_active & (uint8_t)~mask);
    if (handled) {
        vck_result result = update(state, writer, action, down);
        if (result != VCK_OK) {
            state->active[position / 8] = before_active;
            state->physical[position] = before_code;
            return result;
        }
    }
    *out = (cch_event){target_code, (uint8_t)(handled ? CCH_KEYBOARD : CCH_STOCK)};
    return VCK_OK;
}

vck_result ccd_synthetic(cch_state *state, const ccd_writer *writer,
                         uint16_t source, uint8_t down, vck_action action)
{
    unsigned position = (unsigned)source - VCSYN_BUILTIN_BASE;
    uint8_t *owner = &state->builtin[position];
    uint8_t before = *owner;
    if (before != 0) {
        uint16_t packed = cch_rc2_builtin_dictionary[before - 1];
        action = (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed};
    }
    vck_result result = cch_builtin(state, (uint16_t)position, down, action,
                                    cch_rc2_builtin_dictionary, CCH_RC2_BUILTIN_COUNT);
    if (result != VCK_OK || before == *owner) {
        return result;
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
