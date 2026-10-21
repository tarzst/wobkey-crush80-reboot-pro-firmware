/* Independent behavioral scenarios; a host process, never a device client. */
#include <assert.h>
#include <string.h>
#include "macro_stream.h"

static uint8_t basic[8], bitmap[16];

static void emit(void *context, uint8_t modifiers, uint8_t usage, uint8_t down)
{
    (void)context;
    basic[0] = down ? (uint8_t)(basic[0] | modifiers) : (uint8_t)(basic[0] & (uint8_t)~modifiers);
    if (usage == 0) {
        return;
    }
    for (unsigned i = 2; i < 8; ++i) {
        if ((!down && basic[i] == usage) || (down && basic[i] == 0)) {
            basic[i] = down ? usage : 0;
            return;
        }
    }
    assert(!"unexpected overflow in this small scenario");
}

static int contains(uint8_t usage)
{
    for (unsigned i = 2; i < 8; ++i) {
        if (basic[i] == usage) {
            return 1;
        }
    }
    return 0;
}

int main(void)
{
    cm_memory memory;
    cch_event event;
    ccd_writer writer = {basic, bitmap, emit, NULL, 1};
    assert(sizeof(memory) == 512 && sizeof(memory.owners) == 420);
    assert(cm_init(&memory) == VCK_OK);
    bitmap[0] = 1;

    /* A physical GUI and two different chords sharing GUI + Q. */
    assert(ccd_physical(&memory.owners, &writer, 0, 1, 0xe3, &event) == VCK_OK);
    assert(ccd_physical(&memory.owners, &writer, 1, 1, 0x0914, &event) == VCK_OK);
    assert(ccd_physical(&memory.owners, &writer, 2, 1, 0x0814, &event) == VCK_OK);
    assert(basic[0] == 9 && contains(0x14));
    /* Changed release code must not replace the press-time latched action. */
    assert(ccd_physical(&memory.owners, &writer, 1, 0, 0x0a22, &event) == VCK_OK);
    assert(basic[0] == 8 && contains(0x14));
    assert(ccd_physical(&memory.owners, &writer, 2, 0, 0, &event) == VCK_OK);
    assert(basic[0] == 8 && !contains(0x14));

    /* Explicit macro GUI-down survives its temporary Q tap and normal end. */
    const uint8_t bank[512] = {1, 2, 0xe3, 1, 1, 0x14, 0};
    assert(cm_start(&memory, 0, 0) == VCK_OK);
    unsigned seen_q = 0;
    for (unsigned i = 0; i < 200; ++i) {
        int result = cm_step(&memory, &writer, i * CM_TICKS_PER_MS * 8u);
        if (result == CM_STEP_READ) {
            cm_read request;
            assert(cm_prepare_read(&memory, &request) == VCK_OK);
            assert(request.slot == 0 && request.offset <= 512 - CM_CACHE_BYTES);
            memcpy(memory.cache, bank + request.offset, CM_CACHE_BYTES);
            assert(cm_finish_read(&memory, &request, 1) == VCK_OK);
        }
        seen_q |= (unsigned)contains(0x14);
        assert(basic[0] == 8);
    }
    assert(seen_q && memory.engine.phase == CM_IDLE && !contains(0x14));
    assert(cm_cancel(&memory) == VCK_OK);
    for (unsigned i = 0; i < 200 && memory.engine.phase != CM_IDLE; ++i) {
        assert(cm_step(&memory, &writer, 0) >= 0);
    }
    assert(memory.engine.phase == CM_IDLE && basic[0] == 8);
    assert(ccd_physical(&memory.owners, &writer, 0, 0, 0, &event) == VCK_OK);
    assert(basic[0] == 0);

    /* A runtime reset must not release an interrupted cache-fill lease. */
    memory.engine.binding_active = 1;
    assert(cm_reset(&memory, 0) == VCK_OK && memory.engine.binding_active == 1);
    assert(cm_init(&memory) == VCK_OK && memory.engine.binding_active == 0);
    return 0;
}
