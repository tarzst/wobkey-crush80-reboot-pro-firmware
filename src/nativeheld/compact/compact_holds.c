#include "compact_holds.h"

static int bit(const uint8_t *bytes, unsigned index)
{
    return (bytes[index / 8] & (1u << (index % 8))) != 0;
}

static void set(uint8_t *bytes, unsigned index, uint8_t down)
{
    uint8_t mask = (uint8_t)(1u << (index % 8));
    bytes[index / 8] = down ? (uint8_t)(bytes[index / 8] | mask) :
                              (uint8_t)(bytes[index / 8] & (uint8_t)~mask);
}

vck_result cch_decode(uint16_t code, vck_action *out)
{
    vck_action action = {0, 0};
    if (code >= VCK_USAGE_MIN && code <= VCK_USAGE_MAX) {
        action.usage = (uint8_t)code;
    } else if (code == CCH_OEM_KEYCODE) {
        action.usage = CCH_OEM_USAGE;
    } else if (code >= 0xe0 && code <= 0xe7) {
        action.modifiers = (uint8_t)(1u << (code - 0xe0));
    } else if (code >= 0x100 && code <= 0x1fff) {
        uint8_t usage = (uint8_t)code;
        if (usage != 0 && (usage < VCK_USAGE_MIN || usage > VCK_USAGE_MAX)) {
            return VCK_UNSUPPORTED;
        }
        unsigned group = code >> 8;
        action = (vck_action){(uint8_t)((group & 15u) << ((group & 16u) ? 4 : 0)), usage};
    } else if (code != 0) {
        return VCK_UNSUPPORTED;
    }
    *out = action;
    return VCK_OK;
}

__attribute__((noinline)) int cch_keyboard(uint16_t code, vck_action *action)
{
    /* Bare OEM Locking Num/Caps/Scroll codes retain their stock pulses.
     * A QK_MODS-wrapped ordinary usage is a keyboard action, as specified.
     */
    return !(code >= 0x82 && code <= 0x84) && cch_decode(code, action) == VCK_OK;
}

vck_result cch_reset(cch_state *state, uint8_t preserve_stock)
{
    if (!preserve_stock) {
        cdb_memzero(state, sizeof(*state));
        return VCK_OK;
    }
    for (unsigned i = 0; i < CCH_POSITIONS; ++i) {
        vck_action ignored;
        if (!bit(state->active, i) || cch_keyboard(state->physical[i], &ignored)) {
            state->physical[i] = 0;
            set(state->active, i, 0);
        }
    }
    cdb_memzero(state->builtin, sizeof(*state) - offsetof(cch_state, builtin));
    return VCK_OK;
}

vck_result cch_builtin(cch_state *state, uint16_t position, uint8_t down,
                        vck_action action, const uint16_t *dict, uint8_t count)
{
    if (!down) {
        state->builtin[position] = 0;
        return VCK_OK;
    }
    if (state->builtin[position] != 0) {
        return VCK_OK; /* Duplicate press cannot replace its old action. */
    }
    uint16_t packed = (uint16_t)(((uint16_t)action.modifiers << 8) | action.usage);
    for (unsigned i = 0; i < count; ++i) {
        if (dict[i] == packed) {
            state->builtin[position] = (uint8_t)(i + 1);
            return VCK_OK;
        }
    }
    return VCK_UNSUPPORTED;
}

static void include(vck_action *query, uint8_t target, vck_action action)
{
    query->modifiers = (uint8_t)(query->modifiers | action.modifiers);
    if (action.usage == target) {
        query->usage = target;
    }
}

__attribute__((noinline)) vck_result cch_query(const cch_state *state, const uint16_t *dict, uint8_t count,
                                               uint8_t target, vck_action *out)
{
    (void)count;
    vck_action query = {state->macro[0], 0};
    if (target != 0 && target <= VCK_USAGE_MAX && bit(state->macro, 8u + target - VCK_USAGE_MIN)) {
        query.usage = target;
    }
    for (unsigned i = 0; i < CCH_POSITIONS; ++i) {
        vck_action action;
        if (bit(state->active, i) && cch_keyboard(state->physical[i], &action)) {
            include(&query, target, action);
        }
        unsigned index = state->builtin[i];
        if (index != 0) {
            uint16_t packed = dict[index - 1];
            action = (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed};
            include(&query, target, action);
        }
    }
    *out = query;
    return VCK_OK;
}
