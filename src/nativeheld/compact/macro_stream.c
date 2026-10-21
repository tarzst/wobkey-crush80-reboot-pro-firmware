#include "macro_stream.h"

enum { WAITING = 1, HAS_DIGIT = 2, NO_PENDING = 255, INTERVAL_MS = 8 };

static int valid_slot(uint16_t slot)
{
    return slot <= 0xc00 && (slot & 0x1ffu) == 0;
}

static int reading(uint8_t phase)
{
    return phase >= CM_SEEK && phase <= CM_DELAY;
}

static void reset_engine(cm_engine *engine, uint32_t generation)
{
    uint8_t *bytes = (uint8_t *)engine;
    for (unsigned i = 0; i < sizeof(*engine); ++i) {
        bytes[i] = 0;
    }
    engine->generation = generation;
    engine->pending_id = NO_PENDING;
}

vck_result cm_init(cm_memory *memory)
{
    if (memory == NULL) {
        return VCK_INVALID;
    }
    (void)cch_reset(&memory->owners, 0);
    reset_engine(&memory->engine, 1);
    /* Invalid cache bytes are never read until a complete fill is accepted. */
    return VCK_OK;
}

vck_result cm_reset(cm_memory *memory, uint8_t preserve_stock)
{
    if (memory == NULL || preserve_stock > 1) {
        return VCK_INVALID;
    }
    uint32_t generation = memory->engine.generation + 1;
    uint8_t binding_active = memory->engine.binding_active;
    (void)cch_reset(&memory->owners, preserve_stock);
    reset_engine(&memory->engine, generation);
    memory->engine.binding_active = binding_active;
    return VCK_OK;
}

vck_result cm_cancel(cm_memory *memory)
{
    if (memory == NULL) {
        return VCK_INVALID;
    }
    cm_engine *engine = &memory->engine;
    ++engine->generation;
    engine->phase = CM_CANCEL;
    engine->cursor = 0;
    engine->tap_release = 0;
    engine->cache_valid = 0;
    engine->flags = 0;
    engine->pending_id = NO_PENDING;
    return VCK_OK;
}

static void begin(cm_engine *engine, uint8_t id, uint16_t slot)
{
    ++engine->generation;
    engine->phase = CM_SEEK;
    engine->skip = id;
    engine->slot = slot;
    engine->cursor = 0;
    engine->cache_valid = 0;
    engine->flags = 0;
    engine->error = VCK_OK;
    engine->pending_id = NO_PENDING;
}

vck_result cm_start(cm_memory *memory, uint8_t id, uint16_t slot)
{
    if (memory == NULL || id >= CM_MACROS || !valid_slot(slot)) {
        return VCK_INVALID;
    }
    if (memory->engine.phase == CM_IDLE) {
        begin(&memory->engine, id, slot);
    } else {
        (void)cm_cancel(memory);
        memory->engine.pending_id = id;
        memory->engine.pending_slot = slot;
    }
    return VCK_OK;
}

static int fail(cm_memory *memory, vck_result error)
{
    (void)cm_cancel(memory);
    memory->engine.error = (uint8_t)error;
    return CM_STEP_FAILED;
}

static void wait_for(cm_engine *engine, uint32_t now, uint16_t ms)
{
    engine->deadline = now + (uint32_t)ms * CM_TICKS_PER_MS;
    if (ms != 0) {
        engine->flags |= WAITING;
    }
}

static uint16_t ascii_action(uint8_t ascii)
{
    if (ascii >= 'a' && ascii <= 'z') {
        return (uint16_t)(ascii - 'a' + 4);
    }
    if (ascii >= 'A' && ascii <= 'Z') {
        return (uint16_t)(0x0200u | (unsigned)(ascii - 'A' + 4));
    }
    if (ascii >= '1' && ascii <= '9') {
        return (uint16_t)(ascii - '1' + 0x1e);
    }
    if (ascii == '0') {
        return 0x27;
    }
    if (ascii == 8 || ascii == 9) {
        return (uint16_t)(ascii + 0x22);
    }
    if (ascii == 10 || ascii == 13) {
        return 0x28;
    }
    if (ascii == 27 || ascii == 127) {
        return (uint16_t)(ascii == 27 ? 0x29 : 0x4c);
    }
    /* US HID punctuation, bit7 indicates temporary left Shift. */
    static const uint8_t characters[] = " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";
    static const uint8_t actions[] = {
        0x2c, 0x9e, 0xb4, 0xa0, 0xa1, 0xa2, 0xa4, 0x34,
        0xa6, 0xa7, 0xa5, 0xae, 0x36, 0x2d, 0x37, 0x38,
        0xb3, 0x33, 0xb6, 0x2e, 0xb7, 0xb8, 0x9f, 0x2f,
        0x31, 0x30, 0xa3, 0xad, 0x35, 0xaf, 0xb1, 0xb0, 0xb5
    };
    _Static_assert(sizeof(characters) == sizeof(actions) + 1, "ASCII table mismatch");
    for (unsigned i = 0; i < sizeof(actions); ++i) {
        if (characters[i] == ascii) {
            return (uint16_t)((actions[i] & 0x7fu) | ((actions[i] & 0x80u) ? 0x0200u : 0));
        }
    }
    return 0;
}

static int apply(cm_memory *memory, const ccd_writer *writer, uint32_t now,
                   vck_action action, uint8_t opcode)
{
    uint16_t release = 0;
    if (opcode == 1) {
        release = (uint16_t)((uint16_t)(action.modifiers & (uint8_t)~memory->owners.macro[0]) << 8);
        if (action.usage != 0) {
            unsigned bit = 8u + action.usage - VCK_USAGE_MIN;
            if ((memory->owners.macro[bit / 8] & (1u << (bit % 8))) == 0) {
                release = (uint16_t)(release | action.usage);
            }
        }
    }
    vck_result result = ccd_macro_action(&memory->owners, writer, (uint8_t)(opcode != 3), action);
    if (result != VCK_OK) {
        return fail(memory, result);
    }
    cm_engine *engine = &memory->engine;
    engine->tap_release = release;
    engine->phase = release != 0 ? CM_RELEASE : CM_RUN;
    wait_for(engine, now, INTERVAL_MS);
    return CM_STEP_PROGRESS;
}

int cm_step(cm_memory *memory, const ccd_writer *writer, uint32_t now)
{
    if (memory == NULL || writer == NULL) {
        return CM_STEP_FAILED;
    }
    cm_engine *engine = &memory->engine;
    if (engine->phase == CM_CANCEL) {
        while (engine->cursor < CCH_MACRO_BITS) {
            unsigned index = engine->cursor;
            if ((memory->owners.macro[index / 8] & (1u << (index % 8))) != 0) {
                vck_action action = index < 8 ? (vck_action){(uint8_t)(1u << index), 0} :
                                    (vck_action){0, (uint8_t)(index - 8 + VCK_USAGE_MIN)};
                vck_result result = ccd_macro_action(&memory->owners, writer, 0, action);
                if (result != VCK_OK) {
                    engine->error = (uint8_t)result;
                    return CM_STEP_FAILED;
                }
                ++engine->cursor;
                return CM_STEP_PROGRESS;
            }
            ++engine->cursor;
        }
        if (engine->pending_id != NO_PENDING) {
            begin(engine, engine->pending_id, engine->pending_slot);
            return CM_STEP_PROGRESS;
        }
        engine->phase = CM_IDLE;
    }
    if (engine->phase == CM_IDLE) {
        return CM_STEP_IDLE;
    }
    if ((engine->flags & WAITING) != 0) {
        if ((uint32_t)(now - engine->deadline) >= UINT32_C(0x80000000)) {
            return CM_STEP_WAIT;
        }
        engine->flags &= (uint8_t)~WAITING;
    }
    if (engine->phase == CM_FINISH) {
        engine->phase = CM_IDLE;
        return CM_STEP_IDLE;
    }
    if (engine->phase == CM_RELEASE) {
        uint16_t packed = engine->tap_release;
        vck_result result = ccd_macro_action(&memory->owners, writer, 0,
                                            (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed});
        if (result != VCK_OK) {
            return fail(memory, result);
        }
        engine->tap_release = 0;
        engine->phase = CM_RUN;
        wait_for(engine, now, INTERVAL_MS);
        return CM_STEP_PROGRESS;
    }
    if (!reading(engine->phase) || engine->cursor >= CM_BANK_BYTES || !valid_slot(engine->slot)) {
        return fail(memory, VCK_INVALID);
    }
    if (engine->phase == CM_SEEK && engine->skip == 0) {
        engine->phase = CM_RUN;
        return CM_STEP_PROGRESS;
    }
    unsigned line = engine->cursor & ~(CM_CACHE_BYTES - 1u);
    if (!engine->cache_valid || engine->cache_line != line) {
        return CM_STEP_READ;
    }
    uint8_t byte = memory->cache[engine->cursor % CM_CACHE_BYTES];
    ++engine->cursor;
    if (engine->phase == CM_SEEK) {
        if (byte == 0) {
            --engine->skip;
        }
    } else if (engine->phase == CM_RUN) {
        if (byte == 0) {
            engine->phase = CM_IDLE;
            return CM_STEP_IDLE;
        }
        if (byte == 1) {
            engine->phase = CM_PREFIX;
        } else {
            uint16_t packed = ascii_action(byte);
            if (packed == 0) {
                return fail(memory, VCK_UNSUPPORTED);
            }
            return apply(memory, writer, now, (vck_action){(uint8_t)(packed >> 8), (uint8_t)packed}, 1);
        }
    } else if (engine->phase == CM_PREFIX) {
        if (byte >= 1 && byte <= 3) {
            engine->opcode = byte;
            engine->phase = CM_OPERAND;
        } else if (byte == 4) {
            engine->phase = CM_DELAY;
            engine->delay_value = 0;
            engine->flags &= (uint8_t)~HAS_DIGIT;
        } else {
            return fail(memory, VCK_UNSUPPORTED);
        }
    } else if (engine->phase == CM_OPERAND) {
        vck_action action;
        if (byte == 0 || cch_decode(byte, &action) != VCK_OK) {
            return fail(memory, VCK_UNSUPPORTED);
        }
        return apply(memory, writer, now, action, engine->opcode);
    } else {
        if (byte >= '0' && byte <= '9') {
            uint32_t value = (uint32_t)engine->delay_value * 10 + byte - '0';
            if (value > UINT16_MAX) {
                return fail(memory, VCK_UNSUPPORTED);
            }
            engine->delay_value = (uint16_t)value;
            engine->flags |= HAS_DIGIT;
        } else if ((byte == '|' || byte == 0) && (engine->flags & HAS_DIGIT) != 0) {
            engine->phase = byte == 0 ? CM_FINISH : CM_RUN;
            wait_for(engine, now, engine->delay_value);
        } else {
            return fail(memory, VCK_UNSUPPORTED);
        }
    }
    return CM_STEP_PROGRESS;
}

vck_result cm_prepare_read(cm_memory *memory, cm_read *out)
{
    if (memory == NULL || out == NULL || !reading(memory->engine.phase) ||
        memory->engine.cursor >= CM_BANK_BYTES || !valid_slot(memory->engine.slot)) {
        return VCK_INVALID;
    }
    cm_engine *engine = &memory->engine;
    uint16_t offset = (uint16_t)(engine->cursor & ~(CM_CACHE_BYTES - 1u));
    if (engine->cache_valid && engine->cache_line == offset) {
        return VCK_INVALID;
    }
    *out = (cm_read){engine->generation, engine->slot, offset};
    engine->cache_valid = 0;
    return VCK_OK;
}

vck_result cm_finish_read(cm_memory *memory, const cm_read *request, uint8_t success)
{
    if (memory == NULL || request == NULL || success > 1) {
        return VCK_INVALID;
    }
    cm_engine *engine = &memory->engine;
    if (!reading(engine->phase) || request->generation != engine->generation ||
        request->slot != engine->slot || engine->cursor >= CM_BANK_BYTES ||
        request->offset != (engine->cursor & ~(CM_CACHE_BYTES - 1u)) || !valid_slot(request->slot)) {
        return VCK_INVALID;
    }
    if (!success) {
        (void)fail(memory, VCK_INVALID);
        return VCK_INVALID;
    }
    engine->cache_line = request->offset;
    engine->cache_valid = 1;
    return VCK_OK;
}
