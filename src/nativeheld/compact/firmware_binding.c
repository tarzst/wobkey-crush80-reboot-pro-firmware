#include "firmware_binding.h"
#include "../core/oem_b91.h"

#define GP           OEM_GP_ADDR
#define BYTE_AT      OEM_BYTE_AT
#define HALF_AT      OEM_HALF_AT
#define BASIC        OEM_GP_BYTE(OEM_BASIC_OFFSET)
#define BITMAP       OEM_GP_BYTE(OEM_BITMAP_OFFSET)
#define STATUS       OEM_GP_BYTE(OEM_STATUS_OFFSET)
#define PRESSED      OEM_GP_BYTE(OEM_PRESSED_OFFSET)
#define READY        OEM_GP_BYTE(OEM_READY_OFFSET)
#define MACRO_FLAGS  OEM_GP_BYTE(OEM_MACRO_FLAGS_OFFSET)
#define SLOT         OEM_GP_HALF(OEM_MACRO_SLOT_OFFSET)
#define UPLOAD       OEM_GP_HALF(OEM_MACRO_UPLOAD_OFFSET)
#define STAGING      ((uint8_t *)(uintptr_t)(OEM_GP_ADDR + OEM_STAGING_OFFSET))

static int enabled(void)
{
    return *READY > 7 && (*STATUS & 0x40u) == 0;
}

static void emit(void *context, uint8_t modifiers, uint8_t usage, uint8_t down)
{
    (void)context;
    uint8_t before = *PRESSED;
    *PRESSED = down ? 0xff : 0;
    cdb_oem_common(modifiers, usage);
    *PRESSED = before;
}

static ccd_writer writer(void)
{
    return (ccd_writer){BASIC, BITMAP, emit, NULL, (uint8_t)(*OEM_GP_BYTE(OEM_NKRO_OFFSET) != 0)};
}

static void clear(volatile uint8_t *bytes, unsigned length)
{
    for (unsigned i = 0; i < length; ++i) {
        bytes[i] = 0;
    }
}

static void reset(uint8_t matrix)
{
    if (*READY <= 7) {
        (void)cm_init(&cdb_workspace);
    } else {
        (void)cm_reset(&cdb_workspace, (uint8_t)!matrix);
    }
    clear(BASIC, 8);
    clear(BITMAP, 16);
    BITMAP[0] = 1;
    *MACRO_FLAGS &= 0x83u; /* Preserve OEM custom bits0/1 and builtin bit7. */
    *OEM_GP_HALF(OEM_MACRO_TIMER_OFFSET) = 0;
}

int cdb_physical(cdb_frame *frame, uint32_t position)
{
    uint32_t saved = vci_enter();
    if (!enabled() || position >= CCH_POSITIONS || (*PRESSED != 0 && *PRESSED != 0xff)) {
        vci_leave(saved);
        return 0;
    }
    ccd_writer output = writer();
    cch_event event;
    vck_result result = ccd_physical(&cdb_workspace.owners, &output, (uint16_t)position,
                                    (uint8_t)(*PRESSED != 0), (uint16_t)frame->a[3], &event);
    if (result != VCK_OK || event.route != CCH_STOCK || event.code <= 3) {
        vci_leave(saved);
        return 0;
    }
    if (event.code >= 0x82 && event.code <= 0x84) {
        uint8_t usage = event.code == 0x82 ? 0x39 : event.code == 0x83 ? 0x53 : 0x47;
        result = ccd_synthetic(&cdb_workspace.owners, &output,
                               (uint16_t)(VCSYN_BUILTIN_BASE + position), 1, (vck_action){0, usage});
        vci_leave(saved);
        if (result == VCK_OK) {
            cdb_oem_send();
            saved = vci_enter();
            if (enabled()) {
                output = writer();
                (void)ccd_synthetic(&cdb_workspace.owners, &output,
                                    (uint16_t)(VCSYN_BUILTIN_BASE + position), 0, (vck_action){0, usage});
            }
            *PRESSED = 0; /* Same final pulse flag as the OEM locking path. */
            vci_leave(saved);
            cdb_oem_send();
        }
        return 0;
    }
    frame->a[1] = (uint8_t)event.code;
    frame->a[3] = event.code;
    vci_leave(saved);
    return 1;
}

void cdb_synthetic(cdb_frame *frame)
{
    /* Old macro and locking writers are replaced as whole components.
     * Only these surviving builtin callers may enter the shared writer. */
    static const uint16_t callers[] = {0x2bb4, 0x2bd8, 0x2bec, 0x2bfc, 0x2fcc, 0x2fe8,
        0x3950, 0x3960, 0x3974, 0x3984, 0x3998, 0x39ac, 0x39bc, 0x34a8, 0x3668, 0x36d0};
    uint32_t saved = vci_enter();
    uint8_t position = *OEM_GP_BYTE(OEM_POSITION_OFFSET), down = *PRESSED;
    if (enabled() && position < CCH_POSITIONS && (down == 0 || down == 0xff) &&
        frame->a[0] <= 255 && frame->a[1] <= 255 && (frame->ra >> 16) == 0x2001) {
        for (unsigned i = 0; i < sizeof(callers) / sizeof(callers[0]); ++i) {
            if ((uint16_t)frame->ra == callers[i]) {
                ccd_writer output = writer();
                (void)ccd_synthetic(&cdb_workspace.owners, &output,
                                    (uint16_t)(VCSYN_BUILTIN_BASE + position), (uint8_t)(down != 0),
                                    (vck_action){(uint8_t)frame->a[0], (uint8_t)frame->a[1]});
                break;
            }
        }
    }
    vci_leave(saved);
}

void cdb_ready(cdb_frame *frame)
{
    if (frame->a[0] == GP + OEM_READY_OFFSET && frame->a[3] == 8) {
        uint32_t saved = vci_enter();
        (void)cm_init(&cdb_workspace);
        clear(BASIC, 8);
        clear(BITMAP, 16);
        BITMAP[0] = 1;
        *STATUS |= 6;
        vci_leave(saved);
    }
}

void cdb_reset_common(cdb_frame *frame)
{
    uint32_t saved = vci_enter();
    reset(0);
    clear(OEM_GP_BYTE(OEM_CONSUMER_OFFSET), 3);
    clear(OEM_GP_BYTE(OEM_SYSTEM_OFFSET), 3);
    clear(OEM_GP_BYTE(OEM_MOUSE_OFFSET), 8);
    *STATUS |= 0x1e;
    *OEM_GP_BYTE(OEM_STATUS2_OFFSET) |= 0x40;
    /* Exact register results of the replaced OEM common reset. */
    frame->a[0] = frame->a[1] = GP + OEM_MOUSE_TAIL_OFFSET;
    frame->a[3] = (uint32_t)(int32_t)(int8_t)*STATUS;
    frame->a[4] = (uint32_t)(int32_t)(int8_t)*OEM_GP_BYTE(OEM_STATUS2_OFFSET);
    vci_leave(saved);
}

void cdb_reset_finish(cdb_frame *frame, uint32_t s1, uint32_t s0)
{
    /* The matching assembly begin holds MIE off across the OEM zero block.
     * No original SP-relative accesses may occur inside those blocks. */
    uint16_t continuation = (uint16_t)frame->ra;
    reset((uint8_t)(continuation == 0x0c54 || continuation == 0xab34));
    if (continuation == 0x0c54) {
        frame->a[3] = (uint32_t)(int32_t)(int8_t)*STATUS;
    } else if (continuation == 0x10f0 || continuation == 0x296c) {
        frame->a[5] = *STATUS;
    } else if (continuation == 0xab34) {
        *(volatile uint32_t *)(uintptr_t)s0 = frame->a[3];
    } else if (continuation == 0xb75c && (s1 & 2u) == 0) {
        frame->ra = UINT32_C(0x2001b63c);
    }
}

static void take_macro_request(void)
{
    if ((*MACRO_FLAGS & 4u) != 0) {
        uint8_t id = *OEM_GP_BYTE(OEM_MACRO_ID_OFFSET);
        *MACRO_FLAGS &= (uint8_t)~4u;
        if ((*UPLOAD & 0x8000u) == 0) {
            (void)cm_start(&cdb_workspace, id, *SLOT);
        }
    }
}

void cdb_macro_poll(void)
{
    uint32_t saved = vci_enter();
    if (!enabled() || cdb_workspace.engine.binding_active) {
        vci_leave(saved);
        return;
    }
    /* Keep this invocation's ownership across the unguarded flash read.
     * Runtime reset preserves it; a nested poll must not start another fill.
     * Cold cm_init is quiescent and clears the field before READY becomes 8. */
    cdb_workspace.engine.binding_active = 1;
    take_macro_request();
    ccd_writer output = writer();
    uint32_t now = *OEM_WORD_AT(OEM_TIMER_TICK_REG);
    int step = cm_step(&cdb_workspace, &output, now);
    cm_read request;
    if (step == CM_STEP_READ && cm_prepare_read(&cdb_workspace, &request) == VCK_OK) {
        vci_leave(saved);
        cdb_flash_read(OEM_MACRO_FLASH_BASE + request.slot + request.offset,
                        CM_CACHE_BYTES, cdb_workspace.cache);
        saved = vci_enter();
        /* A key IRQ can request a replacement during the unguarded fill.
         * Cancel that old generation before considering its completion. */
        take_macro_request();
        if (cm_finish_read(&cdb_workspace, &request, 1) == VCK_OK && enabled()) {
            output = writer();
            (void)cm_step(&cdb_workspace, &output, *OEM_WORD_AT(OEM_TIMER_TICK_REG));
        }
    }
    if (cdb_workspace.engine.phase == CM_IDLE) {
        *MACRO_FLAGS &= (uint8_t)~8u;
    } else {
        *MACRO_FLAGS |= 8;
    }
    cdb_workspace.engine.binding_active = 0;
    vci_leave(saved);
}

int32_t cdb_macro_scan(uint32_t address, uint8_t *unused, uint32_t length)
{
    (void)unused;
    if (address != OEM_MACRO_FLASH_BASE || length != CM_BANK_BYTES) {
        return -512;
    }
    /* This is the settings-reload bank scan, not a VIA GET_BUFFER read.
     * Establish a fresh report/macro epoch before borrowing the cache. */
    uint32_t saved = vci_enter();
    reset(0);
    *UPLOAD = 0;
    if (*READY > 7) {
        *STATUS |= 6;
    }
    vci_leave(saved);
    int32_t last = -512;
    uint8_t header[4];
    for (unsigned offset = 0; offset <= 0xc00; offset += CM_BANK_BYTES) {
        cdb_flash_read(address + offset, 4, header);
        if ((header[0] & header[1] & header[2] & header[3]) != 255) {
            last = (int32_t)offset;
        }
    }
    return last; /* No full-cache read or destructive journal compaction. */
}

int cdb_macro_empty(uint32_t address, uint32_t length, const uint8_t *unused)
{
    (void)unused;
    if (address != OEM_MACRO_FLASH_BASE || length != CM_BANK_BYTES) {
        return -1;
    }
    uint8_t zeros[CM_CACHE_BYTES];
    clear(zeros, CM_CACHE_BYTES);
    /* Caller has erased the sector. Publish journal first word last. */
    for (unsigned offset = 4; offset < CM_BANK_BYTES; offset += CM_CACHE_BYTES) {
        unsigned size = CM_BANK_BYTES - offset;
        if (size > CM_CACHE_BYTES) {
            size = CM_CACHE_BYTES;
        }
        (void)cdb_flash_program(address + offset, size, zeros);
    }
    return cdb_flash_program(address, 4, zeros);
}

static int erased_slot(uint16_t slot)
{
    /* A torn body write can leave an erased header over programmed data.
     * NOR permits only 1->0 programming; inspect the whole candidate slot,
     * not just its unpublished header, before reusing it. */
    uint8_t bytes[CM_CACHE_BYTES];
    for (unsigned offset = 0; offset < CM_BANK_BYTES; offset += CM_CACHE_BYTES) {
        cdb_flash_read(OEM_MACRO_FLASH_BASE + slot + offset, CM_CACHE_BYTES, bytes);
        for (unsigned i = 0; i < CM_CACHE_BYTES; ++i) {
            if (bytes[i] != 255) {
                return 0;
            }
        }
    }
    return 1;
}

/* Keep the upload transaction outside the command switch: on RV32 their
 * separate register lifetimes need fewer spill slots than one merged body. */
__attribute__((noinline)) void cdb_macro_chunk(uint8_t packet[32])
{
    unsigned offset = (unsigned)packet[1] * 256 + packet[2], size = packet[3];
    if (size > 28 || offset > CM_BANK_BYTES || size > CM_BANK_BYTES - offset) {
        packet[0] = 0xff;
        return;
    }
    if (size == 0) {
        return;
    }
    uint32_t saved = vci_enter();
    if (!enabled()) {
        vci_leave(saved);
        packet[0] = 0xff;
        return;
    }
    (void)cm_cancel(&cdb_workspace);
    vci_leave(saved);
    /* Macro engine is the only macro producer. Physical/builtin IRQ events
     * remain available between short cancellation steps; flash I/O stays
     * outside those guards. */
    do {
        saved = vci_enter();
        if (!enabled()) {
            vci_leave(saved);
            packet[0] = 0xff;
            return;
        }
        ccd_writer output = writer();
        int step = cm_step(&cdb_workspace, &output, 0);
        vci_leave(saved);
        if (step == CM_STEP_FAILED) {
            packet[0] = 0xff;
            return;
        }
    } while (cdb_workspace.engine.phase != CM_IDLE);
    if (offset == CM_BANK_BYTES - 1) {
        if (packet[4] != 0) {
            clear(STAGING, CM_BANK_BYTES);
            *UPLOAD = 0x8000;
            return;
        }
        if ((*UPLOAD & 0x8000u) == 0 ||
            (STAGING[0] & STAGING[1] & STAGING[2] & STAGING[3]) == 255) {
            packet[0] = 0xff;
            return;
        }
        uint16_t current = *SLOT;
        uint16_t next = (uint16_t)(current + CM_BANK_BYTES);
        if (current > 0xc00 || (current & 0x1ffu) != 0) {
            next = 0xe00;
        }
        while (next <= 0xc00 && !erased_slot(next)) {
            next = (uint16_t)(next + CM_BANK_BYTES);
        }
        if (next > 0xc00) {
            cdb_flash_erase(OEM_MACRO_FLASH_BASE);
            next = 0;
        }
        (void)cdb_flash_program(OEM_MACRO_FLASH_BASE + next + 4, CM_BANK_BYTES - 4, STAGING + 4);
        (void)cdb_flash_program(OEM_MACRO_FLASH_BASE + next, 4, STAGING);
        *SLOT = next;
        *UPLOAD = 0;
        return;
    }
    if ((*UPLOAD & 0x8000u) == 0) {
        uint16_t slot = *SLOT;
        if (slot <= 0xc00 && (slot & 0x1ffu) == 0) {
            cdb_flash_read(OEM_MACRO_FLASH_BASE + slot, CM_BANK_BYTES, STAGING);
        } else {
            clear(STAGING, CM_BANK_BYTES);
        }
        *UPLOAD = 0x8000;
    }
    for (unsigned i = 0; i < size; ++i) {
        STAGING[offset + i] = packet[4 + i];
    }
    unsigned end = offset + size, old = *UPLOAD & 0x3ffu;
    *UPLOAD = (uint16_t)(0x8000u | (end > old ? end : old));
}
