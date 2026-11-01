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

__attribute__((always_inline)) static inline int enabled(void)
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

static const ccd_writer cdb_writer = {
    (const volatile uint8_t *)(uintptr_t)(OEM_GP_ADDR + OEM_BASIC_OFFSET),
    (const volatile uint8_t *)(uintptr_t)(OEM_GP_ADDR + OEM_BITMAP_OFFSET),
    emit,
    NULL,
    (const volatile uint8_t *)(uintptr_t)(OEM_GP_ADDR + OEM_NKRO_OFFSET)
};

#define clear(bytes, length) cdb_memzero((bytes), (length))

static void clear_reports(void)
{
    clear(BASIC, 8);
    clear(BITMAP, 16);
    BITMAP[0] = 1;
}

static void reset(uint8_t matrix)
{
    if (*READY <= 7) {
        (void)cm_init(&cdb_workspace);
    } else {
        (void)cm_reset(&cdb_workspace, (uint8_t)!matrix);
    }
    clear_reports();
    *MACRO_FLAGS &= 0x83u; /* Preserve OEM custom bits0/1 and builtin bit7. */
    *OEM_GP_HALF(OEM_MACRO_TIMER_OFFSET) = 0;
}

__attribute__((always_inline)) static inline uint8_t effective_base_layer(void)
{
    cl_state *layers = &cdb_workspace.layers;
    uint8_t cur_mac = *OEM_GP_BYTE(OEM_CONFIG_OFFSET + 26) ? CL_FLAG_LAST_MAC : 0u;
    if ((layers->flags & CL_FLAG_LAST_MAC) != cur_mac) {
        layers->flags = (uint8_t)((layers->flags & ~(CL_FLAG_LAST_MAC | CL_FLAG_DF_OVERRIDE)) | cur_mac);
    }
    return ((layers->flags & CL_FLAG_DF_OVERRIDE) != 0)
        ? (uint8_t)(layers->flags & CL_FLAG_DF_MASK)
        : (cur_mac ? 2u : 0u);
}

__attribute__((noinline)) static uint16_t apply_tap_mods(uint16_t code)
{
    cl_state *layers = &cdb_workspace.layers;
    if ((layers->flags & CL_FLAG_CAPS_WORD) != 0) {
        if (((BASIC[0] | layers->oneshot_mod) & 0xDDu) == 0u &&
            ((uint16_t)(code - 4u) < 36u || code == 0x2Du)) {
            if (code <= 0x1Du || code == 0x2Du) {
                code |= 0x0200u;
            }
        } else if (code != 0x2Au && code != 0x4Cu && (uint16_t)(code - 0xE0u) >= 8u) {
            layers->flags &= (uint8_t)~CL_FLAG_CAPS_WORD;
        }
    }
    if (layers->oneshot_mod != 0 && code <= 0x1FFFu && (uint8_t)(code - 4u) < 0x8Eu) {
        code = (uint16_t)(code | ((uint16_t)layers->oneshot_mod << 8));
        layers->oneshot_mod = 0u;
    }
    return code;
}

__attribute__((noinline)) static uint16_t cdb_key(uint16_t position, uint8_t down, uint16_t code)
{
    cch_event ev;
    if (ccd_physical(&cdb_workspace.owners, &cdb_writer, position, down, code, &ev) == VCK_OK &&
        ev.route == CCH_STOCK && ev.code > 3u) {
        return ev.code;
    }
    return 0u;
}

__attribute__((noinline)) static void check_pending(uint32_t now, uint8_t force)
{
    cl_state *layers = &cdb_workspace.layers;
    uint8_t st = layers->pending_state;
    if (st != CTH_IDLE &&
        (force || (int16_t)((uint16_t)(now >> 8) - layers->pending_deadline) >= 0)) {
        layers->pending_state = CTH_IDLE;
        if (st != CTH_TAPPED) {
            uint8_t arg = layers->pending_arg;
            uint16_t code = (st == CTH_PENDING_MT) ? (uint16_t)((uint16_t)arg << 8) : (uint16_t)(0x5220u | arg);
            if (st == CTH_PENDING_LT) {
                layers->hold_count[arg]++;
            }
            (void)cdb_key(layers->pending_pos, 1, code);
        }
        if (layers->buffered_pos1 != 0) {
            (void)cdb_key((uint16_t)(layers->buffered_pos1 - 1u), 1,
                          apply_tap_mods(layers->buffered_code));
            layers->buffered_pos1 = 0u;
        }
    }
}

int cdb_physical(cdb_frame *frame, uint32_t position)
{
    uint32_t saved = vci_enter();
    uint8_t raw_down = *PRESSED;
    if (!enabled() || position >= CCH_POSITIONS || (raw_down != 0 && raw_down != 0xff)) {
        goto done;
    }
    uint8_t down = (uint8_t)(raw_down != 0);
    if (down && (cdb_workspace.owners.active[position / 8u] & (uint8_t)(1u << (position % 8u))) != 0) {
        goto done;
    }
    uint32_t now = *OEM_WORD_AT(OEM_TIMER_TICK_REG);
    cl_state *layers = &cdb_workspace.layers;
    check_pending(now, (uint8_t)(down && (layers->pending_state == CTH_PENDING_LT || layers->buffered_pos1 != 0)));
    uint8_t base = effective_base_layer();

    uint16_t code = 0;
    if (!down) {
        if (layers->pending_state != CTH_IDLE && layers->pending_state != CTH_TAPPED) {
            if (layers->pending_pos == (uint8_t)position) {
                code = layers->pending_tap_kc;
                layers->pending_state = CTH_TAPPED;
                layers->pending_deadline = (uint16_t)((uint16_t)(now >> 8) + CTH_TAPPING_TERM_TICKS);
                goto tap_pulse;
            }
            if (layers->buffered_pos1 == (uint8_t)(position + 1u)) {
                code = layers->buffered_code;
                layers->buffered_pos1 = 0u;
                check_pending(now, 1u);
tap_pulse:
                code = apply_tap_mods(code);
                goto do_pulse;
            }
        }
        if (layers->lm_layer != 0 && layers->lm_pos == (uint8_t)position) {
            uint8_t l = (uint8_t)(layers->lm_layer - 1u);
            if (layers->hold_count[l] != 0) {
                layers->hold_count[l]--;
            }
            layers->lm_layer = 0u;
        }
        if (layers->osm_mod != 0 && layers->osm_pos == (uint8_t)position) {
            if ((layers->flags & CL_FLAG_MOMENTARY_USED) == 0) {
                layers->oneshot_mod = (((layers->oneshot_mod ^ layers->osm_mod) & 0x10u) != 0)
                    ? layers->osm_mod
                    : (uint8_t)(layers->oneshot_mod | layers->osm_mod);
            }
            layers->osm_mod = 0u;
        }
    } else {
        uint8_t layer_mask = (uint8_t)(layers->toggle_mask | layers->oneshot_mask | (1u << base) | 1u);
        for (unsigned l = 0; l < VCK_LAYERS; ++l) {
            if (layers->hold_count[l] != 0) {
                layer_mask |= (uint8_t)(1u << l);
            }
        }
        if (layers->tri_count != 0 && (layer_mask & 6u) == 6u) {
            layer_mask |= 8u;
        }
        uint32_t seq = 0x01bu | ((uint32_t)base << 8);
        const volatile uint8_t *keymap = OEM_BYTE_AT(OEM_GP_ADDR - OEM_KEYMAP_NEG_OFFSET) + (position << 1);
        for (unsigned step = 0; step < 6u; ++step, seq >>= 2) {
            unsigned layer = seq & 3u;
            if ((layer_mask & (1u << layer)) != 0) {
                uint16_t c = (uint16_t)(((uint16_t)keymap[layer << 8] << 8) | keymap[(layer << 8) + 1u]);
                if (c != 0x0001u) {
                    code = c;
                    break;
                }
            }
        }
        uint8_t hi = (uint8_t)(code >> 8);
        uint8_t lo = (uint8_t)code;
        if ((code & 0xFFFEu) == 0x5F10u || (code & 0xFFFEu) == 0x7700u) {
            code = (uint16_t)(0x52E1u + (lo & 1u));
            hi = 0x52u;
        } else if ((code & 0xFFE0u) == 0x52A0u) {
            layers->osm_pos = (uint8_t)position;
            layers->osm_mod = (uint8_t)(lo & 0x1Fu);
            layers->flags &= (uint8_t)~CL_FLAG_MOMENTARY_USED;
            code = (uint16_t)((uint16_t)layers->osm_mod << 8);
        } else if ((code & 0xFF80u) == 0x5000u && (lo & 0x0Fu) != 0) {
            uint8_t l = (uint8_t)((lo >> 5) & 3u);
            layers->hold_count[l]++;
            layers->lm_pos = (uint8_t)position;
            layers->lm_layer = (uint8_t)(l + 1u);
            code = (uint16_t)((uint16_t)(lo & 0x1Fu) << 8);
            hi = 0x52u;
        } else if (code == 0x7C73u) {
            layers->flags ^= CL_FLAG_CAPS_WORD;
            goto done;
        }
        if (hi != 0x52u) {
            layers->oneshot_mask = 0u;
            layers->flags |= CL_FLAG_MOMENTARY_USED;
            if (layers->pending_state == CTH_PENDING_MT &&
                code <= 0x1FFFu && (uint8_t)(lo - 4u) < 0x8Eu) {
                layers->buffered_pos1 = (uint8_t)(position + 1u);
                layers->buffered_code = code;
                goto done;
            }
            uint8_t quick_tap = (uint8_t)(layers->pending_state == CTH_TAPPED &&
                                          layers->pending_pos == (uint8_t)position);
            check_pending(now, 1u);
            if (code == 0x7C16u || code == 0x5C16u) {
                code = (((BASIC[0] & 0xAAu) | (layers->oneshot_mod & 0x0Au)) != 0u) ? 0x35u : 0x29u;
            }
            if (code >= 0x2000u && code <= 0x4FFFu) {
                if (code < 0x4400u) {
                    if (quick_tap) {
                        code = apply_tap_mods(lo);
                    } else {
                        uint8_t is_lt = (code >= 0x4000u);
                        uint8_t arg = (uint8_t)(hi & (is_lt ? 3u : 0x1Fu));
                        layers->pending_state = is_lt ? CTH_PENDING_LT : CTH_PENDING_MT;
                        layers->pending_pos = (uint8_t)position;
                        layers->pending_arg = (!is_lt && (arg & 0x0Fu) == 0) ? 1u : arg;
                        layers->pending_tap_kc = lo;
                        layers->pending_deadline = (uint16_t)((uint16_t)(now >> 8) + CTH_TAPPING_TERM_TICKS);
                        goto done;
                    }
                } else {
                    goto done;
                }
            } else {
                code = apply_tap_mods(code);
            }
        }
    }

    uint16_t stock = cdb_key((uint16_t)position, down, code);
    if (stock == 0u) {
        if (down && (code == 0xE1u || code == 0xE5u) && BASIC[0] == 0x22u) {
            layers->flags ^= CL_FLAG_CAPS_WORD;
        }
done:
        vci_leave(saved);
        return 0;
    }
    code = stock;
    uint8_t hi = (uint8_t)(code >> 8);
    uint8_t lo = (uint8_t)code;
    if (hi == 0x52u) {
        uint8_t l_arg = (uint8_t)(lo & 0x1Fu);
        uint8_t kind = (uint8_t)(lo & 0xE0u);
        if (l_arg < VCK_LAYERS) {
            uint8_t bit = (uint8_t)(1u << l_arg);
            if (down) {
                if (kind == 0x00u) {
                    layers->toggle_mask = (l_arg == base) ? 0u : bit;
                    layers->oneshot_mask = 0u;
                } else if (kind == 0x40u) {
                    layers->flags = (uint8_t)((layers->flags & ~CL_FLAG_DF_MASK) | l_arg | CL_FLAG_DF_OVERRIDE);
                } else if (kind == 0x60u) {
                    layers->toggle_mask ^= bit;
                } else if (kind == 0x20u || kind >= 0x80u) {
                    layers->hold_count[l_arg]++;
                    layers->flags &= (uint8_t)~CL_FLAG_MOMENTARY_USED;
                    if (kind == 0x80u) {
                        layers->oneshot_mask |= bit;
                    } else if (kind == 0xE0u) {
                        layers->tri_count++;
                    }
                }
            } else if (kind == 0x20u || kind >= 0x80u) {
                if (layers->hold_count[l_arg] != 0) {
                    layers->hold_count[l_arg]--;
                }
                if (kind == 0x80u && (layers->flags & CL_FLAG_MOMENTARY_USED) != 0) {
                    layers->oneshot_mask &= (uint8_t)~bit;
                } else if (kind == 0xC0u && (layers->flags & CL_FLAG_MOMENTARY_USED) == 0) {
                    layers->toggle_mask ^= bit;
                } else if (kind == 0xE0u && layers->tri_count != 0) {
                    layers->tri_count--;
                }
            }
        }
        goto done;
    }
    if (code >= 0x82u && code <= 0x84u) {
        if (!down) {
            goto done;
        }
        code = (lo == 0x82u) ? 0x39u : (lo == 0x83u) ? 0x53u : 0x47u;
do_pulse:
        (void)cdb_key((uint16_t)position, 1, code);
        vci_leave(saved);
        cdb_oem_send();
        saved = vci_enter();
        if (enabled()) {
            (void)cdb_key((uint16_t)position, 0, 0);
            if (layers->buffered_pos1 != 0) {
                check_pending(0u, 1u);
            }
        }
        *PRESSED = 0;
        vci_leave(saved);
        cdb_oem_send();
        return 0;
    }
    frame->a[1] = lo;
    frame->a[3] = code;
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
                (void)ccd_synthetic(&cdb_workspace.owners, &cdb_writer,
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
        clear_reports();
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

void cdb_macro_poll(void)
{
    uint32_t saved = vci_enter();
    if (enabled() && !cdb_workspace.engine.binding_active) {
        cdb_workspace.engine.binding_active = 1;
        *OEM_WORD_AT(OEM_WD_TARGET_REG) = OEM_WD_TARGET_4S;
        *OEM_BYTE_AT(OEM_WD_CTRL2_REG) = OEM_WD_ENABLE_BIT;
        *OEM_BYTE_AT(OEM_WD_STATUS_REG) = OEM_WD_CLEAR_MASK;
        check_pending(*OEM_WORD_AT(OEM_TIMER_TICK_REG), 0);
        for (int tries = 0;; ++tries) {
            if ((*MACRO_FLAGS & 4u) != 0) {
                uint8_t id = *OEM_GP_BYTE(OEM_MACRO_ID_OFFSET);
                *MACRO_FLAGS &= (uint8_t)~4u;
                if ((*UPLOAD & 0x8000u) == 0) {
                    (void)cm_start(&cdb_workspace, id, *SLOT);
                }
            }
            cm_read request;
            if (!enabled() ||
                cm_step(&cdb_workspace, &cdb_writer, *OEM_WORD_AT(OEM_TIMER_TICK_REG)) != CM_STEP_READ ||
                tries != 0 ||
                cm_prepare_read(&cdb_workspace, &request) != VCK_OK) {
                break;
            }
            vci_leave(saved);
            cdb_flash_read(OEM_MACRO_FLASH_BASE + request.slot + request.offset,
                           CM_CACHE_BYTES, cdb_workspace.cache);
            saved = vci_enter();
            if (cm_finish_read(&cdb_workspace, &request, 1) != VCK_OK) {
                break;
            }
        }
        if (cdb_workspace.engine.phase == CM_IDLE && cdb_workspace.layers.pending_state == CTH_IDLE) {
            *MACRO_FLAGS &= (uint8_t)~8u;
        } else {
            *MACRO_FLAGS |= 8;
        }
        cdb_workspace.engine.binding_active = 0;
    }
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
    clear(cdb_workspace.cache, CM_CACHE_BYTES);
    /* Caller has erased the sector. Publish journal first word last. */
    for (unsigned offset = CM_CACHE_BYTES; offset < CM_BANK_BYTES; offset += CM_CACHE_BYTES) {
        (void)cdb_flash_program(address + offset, CM_CACHE_BYTES, cdb_workspace.cache);
    }
    (void)cdb_flash_program(address + 4, CM_CACHE_BYTES - 4, cdb_workspace.cache);
    return cdb_flash_program(address, 4, cdb_workspace.cache);
}

__attribute__((always_inline)) static inline int erased_slot(uint16_t slot)
{
    /* A torn body write can leave an erased header over programmed data.
     * NOR permits only 1->0 programming; inspect the whole candidate slot,
     * not just its unpublished header, before reusing it. */
    for (unsigned offset = 0; offset < CM_BANK_BYTES; offset += CM_CACHE_BYTES) {
        cdb_flash_read(OEM_MACRO_FLASH_BASE + slot + offset, CM_CACHE_BYTES, cdb_workspace.cache);
        for (unsigned i = 0; i < CM_CACHE_BYTES; ++i) {
            if (cdb_workspace.cache[i] != 255) {
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
        goto fail;
    }
    if (size == 0) {
        return;
    }
    uint32_t saved = vci_enter();
    if (!enabled()) {
        vci_leave(saved);
        goto fail;
    }
    (void)cm_cancel(&cdb_workspace);
    while (cdb_workspace.engine.phase != CM_IDLE) {
        (void)cm_step(&cdb_workspace, &cdb_writer, 0);
    }
    vci_leave(saved);
    if (offset == CM_BANK_BYTES - 1) {
        if (packet[4] != 0) {
            clear(STAGING, CM_BANK_BYTES);
            *UPLOAD = 0x8000;
            return;
        }
        if ((*UPLOAD & 0x8000u) == 0 ||
            (STAGING[0] & STAGING[1] & STAGING[2] & STAGING[3]) == 255) {
fail:
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
