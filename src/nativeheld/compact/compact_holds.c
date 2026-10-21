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
    if (out == NULL) {
        return VCK_INVALID;
    }
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

static int keyboard(uint16_t code, vck_action *action)
{
    /* Bare OEM Locking Num/Caps/Scroll codes retain their stock pulses.
     * A QK_MODS-wrapped ordinary usage is a keyboard action, as specified.
     */
    return !(code >= 0x82 && code <= 0x84) && cch_decode(code, action) == VCK_OK;
}

vck_result cch_reset(cch_state *state, uint8_t preserve_stock)
{
    if (state == NULL || preserve_stock > 1) {
        return VCK_INVALID;
    }
    if (!preserve_stock) {
        /* Also initializes padding and never reads uninitialized active bits. */
        uint8_t *bytes = (uint8_t *)state;
        for (unsigned i = 0; i < sizeof(*state); ++i) {
            bytes[i] = 0;
        }
        return VCK_OK;
    }
    for (unsigned i = 0; i < CCH_POSITIONS; ++i) {
        vck_action ignored;
        if (!bit(state->active, i) || keyboard(state->physical[i], &ignored)) {
            state->physical[i] = 0;
            set(state->active, i, 0);
        }
        state->builtin[i] = 0;
    }
    for (unsigned i = 0; i < CCH_MACRO_BYTES; ++i) {
        state->macro[i] = 0;
    }
    return VCK_OK;
}

vck_result cch_physical(cch_state *state, uint16_t position, uint8_t down,
                         uint16_t selected_code, cch_event *out)
{
    if (state == NULL || position >= CCH_POSITIONS || down > 1 || out == NULL) {
        return VCK_INVALID;
    }
    cch_event event = {0, CCH_NONE};
    int active = bit(state->active, position);
    if ((down != 0) == active) {
        *out = event;
        return VCK_OK;
    }
    uint16_t code = down ? selected_code : state->physical[position];
    vck_action ignored;
    int handled = keyboard(code, &ignored);
    /* An unsupported QK_MODS must not fall into an unrelated OEM code family.
     * The selected-code value on release is intentionally never examined.
     */
    if (down && !handled && code >= 0x100 && code <= 0x1fff) {
        return VCK_UNSUPPORTED;
    }
    event.code = code;
    event.route = handled ? CCH_KEYBOARD : CCH_STOCK;
    state->physical[position] = down ? code : 0;
    set(state->active, position, down);
    *out = event;
    return VCK_OK;
}

vck_result cch_builtin(cch_state *state, uint16_t position, uint8_t down,
                        vck_action action, const uint16_t *dict, uint8_t count)
{
    if (state == NULL || position >= CCH_POSITIONS || down > 1) {
        return VCK_INVALID;
    }
    if (!down) {
        state->builtin[position] = 0;
        return VCK_OK;
    }
    if (state->builtin[position] != 0) {
        return VCK_OK; /* Duplicate press cannot replace its old action. */
    }
    if ((count != 0 && dict == NULL) ||
        (action.usage != 0 && (action.usage < VCK_USAGE_MIN || action.usage > VCK_USAGE_MAX))) {
        return VCK_INVALID;
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

vck_result cch_macro_modifier(cch_state *state, uint16_t modifier, uint8_t down)
{
    if (state == NULL || modifier >= 8 || down > 1) {
        return VCK_INVALID;
    }
    set(state->macro, modifier, down);
    return VCK_OK;
}

vck_result cch_macro_usage(cch_state *state, uint16_t usage, uint8_t down)
{
    if (state == NULL || down > 1) {
        return VCK_INVALID;
    }
    if (usage == 0) {
        return VCK_OK;
    }
    if (usage < VCK_USAGE_MIN || usage > VCK_USAGE_MAX) {
        return VCK_UNSUPPORTED;
    }
    set(state->macro, 8u + usage - VCK_USAGE_MIN, down);
    return VCK_OK;
}

static void include(vck_report *report, vck_action *query, uint8_t target, vck_action action)
{
    query->modifiers = (uint8_t)(query->modifiers | action.modifiers);
    if (action.usage == target) {
        query->usage = target;
    }
    if (report != NULL && action.usage != 0) {
        set(report->usages, (unsigned)action.usage - VCK_USAGE_MIN, 1);
    }
}

/* One owner traversal for both full reports and delta queries. The binding
 * only needs one usage per event, so it need not build an unused bitmap.
 * Local outputs keep invalid dictionary/state failures atomic for callers.
 */
static vck_result collect(const cch_state *state, const uint16_t *dict, uint8_t count,
                            uint8_t target, vck_report *report, vck_action *query)
{
    if (state == NULL || (count != 0 && dict == NULL) ||
        (state->macro[CCH_MACRO_BYTES - 1] & 0xc0u) != 0) {
        return VCK_INVALID;
    }
    *query = (vck_action){state->macro[0], 0};
    if (target != 0 && target <= VCK_USAGE_MAX && bit(state->macro, 8u + target - VCK_USAGE_MIN)) {
        query->usage = target;
    }
    if (report != NULL) {
        for (unsigned i = 0; i < VCK_USAGE_BYTES; ++i) {
            report->usages[i] = state->macro[1 + i];
        }
    }
    for (unsigned i = 0; i < CCH_POSITIONS; ++i) {
        vck_action action;
        if (bit(state->active, i) && keyboard(state->physical[i], &action)) {
            if (report != NULL && action.usage > VCK_USAGE_MAX) {
                return VCK_UNSUPPORTED;
            }
            include(report, query, target, action);
        }
        unsigned index = state->builtin[i];
        if (index != 0) {
            if (index > count) {
                return VCK_INVALID;
            }
            uint16_t packed = dict[index - 1];
            action = (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed};
            if (action.usage != 0 && (action.usage < VCK_USAGE_MIN || action.usage > VCK_USAGE_MAX)) {
                return VCK_INVALID;
            }
            include(report, query, target, action);
        }
    }
    if (report != NULL) {
        report->modifiers = query->modifiers;
    }
    return VCK_OK;
}

vck_result cch_report(const cch_state *state, const uint16_t *dict, uint8_t count,
                       vck_report *out)
{
    if (out == NULL) {
        return VCK_INVALID;
    }
    vck_report report;
    vck_action query;
    vck_result result = collect(state, dict, count, 0, &report, &query);
    if (result == VCK_OK) {
        *out = report;
    }
    return result;
}

vck_result cch_query(const cch_state *state, const uint16_t *dict, uint8_t count,
                      uint8_t usage, vck_action *out)
{
    if (out == NULL || (usage != 0 && usage != CCH_OEM_USAGE &&
                        (usage < VCK_USAGE_MIN || usage > VCK_USAGE_MAX))) {
        return VCK_INVALID;
    }
    vck_action query;
    vck_result result = collect(state, dict, count, usage, NULL, &query);
    if (result == VCK_OK) {
        *out = query;
    }
    return result;
}

int cch_idle(const cch_state *state)
{
    if (state == NULL) {
        return 0;
    }
    /* The header statically checks the three byte arrays are contiguous.
     * Read via the enclosing object's byte representation, not by walking
     * outside any individual array. Ignore the trailing alignment padding.
     */
    const uint8_t *bytes = (const uint8_t *)state;
    for (unsigned i = offsetof(cch_state, active);
         i < offsetof(cch_state, macro) + CCH_MACRO_BYTES; ++i) {
        if (bytes[i] != 0) {
            return 0;
        }
    }
    return 1;
}
