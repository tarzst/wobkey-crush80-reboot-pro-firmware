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

__attribute__((noinline)) void cdb_memzero(volatile void *ptr, unsigned len)
{
    volatile uint8_t *p = (volatile uint8_t *)ptr;
    while (len--) {
        *p++ = 0;
    }
}

static void reset_engine(cm_engine *engine, uint32_t generation)
{
    cdb_memzero(engine, sizeof(*engine));
    engine->generation = generation;
    engine->pending_id = NO_PENDING;
}

__attribute__((noinline)) vck_result cm_init(cm_memory *memory)
{
    cdb_memzero(memory, sizeof(*memory));
    memory->engine.generation = 1;
    memory->engine.pending_id = NO_PENDING;
    return VCK_OK;
}

vck_result cm_reset(cm_memory *memory, uint8_t preserve_stock)
{
    uint32_t generation = memory->engine.generation + 1;
    uint8_t binding_active = memory->engine.binding_active;
    if (!preserve_stock) {
        uint8_t toggle = memory->layers.toggle_mask;
        uint8_t kept_flags = (uint8_t)(memory->layers.flags & (CL_FLAG_DF_MASK | CL_FLAG_DF_OVERRIDE | CL_FLAG_LAST_MAC));
        (void)cm_init(memory);
        memory->layers.toggle_mask = toggle;
        memory->layers.flags = kept_flags;
    } else {
        (void)cch_reset(&memory->owners, 1);
        reset_engine(&memory->engine, generation);
        memory->layers.pending_state = CTH_IDLE;
        memory->layers.buffered_pos1 = 0u;
    }
    memory->engine.generation = generation;
    memory->engine.binding_active = binding_active;
    return VCK_OK;
}

vck_result cm_cancel(cm_memory *memory)
{
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

static void begin(cm_memory *memory, uint8_t id, uint16_t slot)
{
    (void)cm_cancel(memory);
    memory->engine.phase = CM_SEEK;
    memory->engine.skip = id;
    memory->engine.slot = slot;
    memory->engine.error = VCK_OK;
}

vck_result cm_start(cm_memory *memory, uint8_t id, uint16_t slot)
{
    if (id >= CM_MACROS || !valid_slot(slot)) {
        return VCK_INVALID;
    }
    if (memory->engine.phase == CM_IDLE) {
        begin(memory, id, slot);
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
    unsigned lower = (unsigned)(ascii | 0x20u) - 'a';
    if (lower < 26u) {
        return (uint16_t)((lower + 4u) | ((ascii & 0x20u) ? 0u : 0x0200u));
    }
    if ((unsigned)(ascii - '1') < 9u) {
        return (uint16_t)(ascii - '1' + 0x1eu);
    }
    /* US HID punctuation + control/0, bit7 indicates temporary left Shift. */
    static const uint8_t characters[40] = {
        '0', 0x08, 0x09, 0x0a, 0x0d, 0x1b, 0x7f,
        ' ', '!', '"', '#', '$', '%', '&', '\'',
        '(', ')', '*', '+', ',', '-', '.', '/',
        ':', ';', '<', '=', '>', '?', '@', '[',
        '\\', ']', '^', '_', '`', '{', '|', '}', '~'
    };
    static const uint8_t actions[40] = {
        0x27, 0x2a, 0x2b, 0x28, 0x28, 0x29, 0x4c,
        0x2c, 0x9e, 0xb4, 0xa0, 0xa1, 0xa2, 0xa4, 0x34,
        0xa6, 0xa7, 0xa5, 0xae, 0x36, 0x2d, 0x37, 0x38,
        0xb3, 0x33, 0xb6, 0x2e, 0xb7, 0xb8, 0x9f, 0x2f,
        0x31, 0x30, 0xa3, 0xad, 0x35, 0xaf, 0xb1, 0xb0, 0xb5
    };
    for (unsigned i = 0; i < sizeof(actions); ++i) {
        if (characters[i] == ascii) {
            return (uint16_t)((actions[i] & 0x7fu) | ((actions[i] & 0x80u) ? 0x0200u : 0));
        }
    }
    return 0;
}

static __attribute__((noinline)) int macro_emit(cm_memory *memory, const ccd_writer *writer, uint8_t down, uint8_t mod, uint8_t usage)
{
    vck_result result = ccd_macro_action(&memory->owners, writer, down, (vck_action){mod, usage});
    if (result != VCK_OK) {
        return fail(memory, result);
    }
    return CM_STEP_PROGRESS;
}

int cm_step(cm_memory *memory, const ccd_writer *writer, uint32_t now)
{
    cm_engine *engine = &memory->engine;
    if (engine->phase == CM_CANCEL) {
        while (engine->cursor < CCH_MACRO_BITS) {
            unsigned index = engine->cursor++;
            if ((memory->owners.macro[index / 8] & (1u << (index % 8))) != 0) {
                uint8_t mod = index < 8 ? (uint8_t)(1u << index) : 0;
                uint8_t usage = index < 8 ? 0 : (uint8_t)(index - 8 + VCK_USAGE_MIN);
                return macro_emit(memory, writer, 0, mod, usage);
            }
        }
        if (engine->pending_id != NO_PENDING) {
            begin(memory, engine->pending_id, engine->pending_slot);
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
        if (macro_emit(memory, writer, 0, (uint8_t)(packed >> 8), (uint8_t)packed) < 0) {
            return CM_STEP_FAILED;
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
            uint8_t mod = (uint8_t)(packed >> 8);
            uint8_t usage = (uint8_t)packed;
            uint8_t opcode = 1;
            if (0) {
            do_operand:
                mod = (byte >= 0xe0u && byte <= 0xe7u) ? (uint8_t)(1u << (byte - 0xe0u)) : 0u;
                usage = (byte >= VCK_USAGE_MIN && byte <= VCK_USAGE_MAX) ? byte : 0u;
                opcode = engine->opcode;
            }
            if ((mod | usage) == 0u) {
                return fail(memory, VCK_UNSUPPORTED);
            }
            uint16_t release = 0;
            if (opcode == 1) {
                release = (uint16_t)((uint16_t)(mod & (uint8_t)~memory->owners.macro[0]) << 8);
                if (usage != 0) {
                    unsigned bit = 8u + usage - VCK_USAGE_MIN;
                    if ((memory->owners.macro[bit / 8] & (1u << (bit % 8))) == 0) {
                        release = (uint16_t)(release | usage);
                    }
                }
            }
            if (macro_emit(memory, writer, (uint8_t)(opcode != 3), mod, usage) < 0) {
                return CM_STEP_FAILED;
            }
            engine->tap_release = release;
            engine->phase = release != 0 ? CM_RELEASE : CM_RUN;
            wait_for(engine, now, INTERVAL_MS);
            return CM_STEP_PROGRESS;
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
        goto do_operand;
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
    cm_engine *engine = &memory->engine;
    *out = (cm_read){engine->generation, engine->slot, (uint16_t)(engine->cursor & ~(CM_CACHE_BYTES - 1u))};
    engine->cache_valid = 0;
    return VCK_OK;
}

vck_result cm_finish_read(cm_memory *memory, const cm_read *request, uint8_t success)
{
    cm_engine *engine = &memory->engine;
    if (!reading(engine->phase) || request->generation != engine->generation) {
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
