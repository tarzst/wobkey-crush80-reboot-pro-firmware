#ifndef CRUSH80_MACRO_STREAM_H
#define CRUSH80_MACRO_STREAM_H

#include "delta_adapter.h"

enum {
    CM_BANK_BYTES = 512, CM_CACHE_BYTES = 32, CM_MACROS = 16,
    CM_TICKS_PER_MS = 16000,
    CM_IDLE = 0, CM_SEEK, CM_RUN, CM_PREFIX, CM_OPERAND, CM_DELAY,
    CM_RELEASE, CM_FINISH, CM_CANCEL,
    CM_STEP_FAILED = -1, CM_STEP_IDLE = 0, CM_STEP_PROGRESS = 1,
    CM_STEP_WAIT = 2, CM_STEP_READ = 3,
    CTH_TAPPING_TERM_TICKS = 12500u, /* 200 ms in (16 MHz >> 8) = 62.5 kHz ticks */
    CTH_IDLE = 0,
    CTH_PENDING_MT = 1,
    CTH_PENDING_LT = 2,
    CL_FLAG_DF_MASK = 0x03u,
    CL_FLAG_DF_OVERRIDE = 0x04u,
    CL_FLAG_LAST_MAC = 0x08u,
    CL_FLAG_MOMENTARY_USED = 0x10u,
    CL_EVENT_HANDLED = 0,
    CL_EVENT_PULSE = 1,
    CL_EVENT_STOCK = 2
};

typedef struct {
    uint8_t hold_count[VCK_LAYERS];
    uint8_t toggle_mask;
    uint8_t oneshot_mask;
    uint8_t flags;
    uint8_t tri_count;
    uint8_t pending_state;
    uint8_t pending_pos;
    uint8_t pending_arg;
    uint8_t pending_tap_kc;
    uint16_t pending_deadline;
    uint8_t oneshot_mod;
    uint8_t osm_pos;
    uint8_t osm_mod;
    uint8_t lm_pos;
    uint8_t lm_layer;
    uint8_t reserved[13];
} cl_state;

typedef struct {
    uint32_t generation;
    uint32_t deadline;
    uint16_t cursor;
    uint16_t slot;
    uint16_t tap_release;
    uint16_t cache_line;
    uint16_t delay_value;
    uint8_t phase;
    uint8_t skip;
    uint8_t cache_valid;
    uint8_t opcode;
    uint8_t flags;
    uint8_t error;
    uint8_t pending_id;
    uint8_t binding_active;
    uint16_t pending_slot;
} cm_engine;

typedef struct {
    cch_state owners;
    cm_engine engine;
    uint8_t cache[CM_CACHE_BYTES];
    cl_state layers;
} cm_memory;

typedef struct {
    uint32_t generation;
    uint16_t slot;
    uint16_t offset;
} cm_read;

_Static_assert(sizeof(cm_engine) == 28, "macro engine metadata changed");
_Static_assert(sizeof(cl_state) == 32, "layer state metadata changed");
_Static_assert(offsetof(cm_memory, engine) == 420 && offsetof(cm_memory, cache) == 448 &&
               offsetof(cm_memory, layers) == 480 && sizeof(cm_memory) == 512,
               "macro workspace no longer fits original cache");

/* Offline component. No firmware address, flash I/O, IRQ or transport binding.
 * The caller serializes each API with all owner/report mutations. init is
 * quiescent and initializes owners/metadata; reset also requires matching OEM
 * report reset. The emitter follows delta_adapter.h's synchronous contract.
 * binding_active is owned by the firmware binding's long-running operation,
 * not the playback state machine. init clears it; reset preserves it, so a
 * reset cannot release an interrupted binding invocation's ownership.
 * step does bounded work and never waits or reads flash. Its clock argument
 * is a wrapping 32-bit 16MHz counter. Poll at least once per half-wrap (134s),
 * or reset/cancel on sleep/wake; maximum accepted delay is 65535ms.
 *
 * On STEP_READ: prepare_read under a short guard, fill exactly cache[0..64)
 * from bank89000 + request.slot + request.offset OUTSIDE the guard, then
 * finish_read under a guard. There may be only one in-flight cache fill.
 * A stale fill may change cache bytes but cannot validate them or touch
 * owners/metadata. Do not start another fill until the previous one returns.
 * All callers other than that fill must leave cache bytes alone.
 *
 * Normal end retains explicit DOWN contributions, as VIA commands require.
 * Temporary taps release only their newly introduced components. Cancelling
 * or malformed input releases only macro contributions, one action per step.
 * A replacement start waits for that cancellation. Upload/erase must wait
 * for cancellation to reach IDLE before changing the macro bank/slot.
 */
vck_result cm_init(cm_memory *memory);
vck_result cm_reset(cm_memory *memory, uint8_t preserve_stock);
void cdb_memzero(volatile void *ptr, unsigned len);
vck_result cm_start(cm_memory *memory, uint8_t id, uint16_t slot);
vck_result cm_cancel(cm_memory *memory);
int cm_step(cm_memory *memory, const ccd_writer *writer, uint32_t now);
vck_result cm_prepare_read(cm_memory *memory, cm_read *out);
vck_result cm_finish_read(cm_memory *memory, const cm_read *request, uint8_t success);

uint16_t cl_resolve_keycode(
    cl_state *layers,
    const volatile uint8_t *keymap,
    uint8_t mac_mode,
    uint8_t position
);
void cl_poll(cm_memory *memory, const ccd_writer *writer, uint32_t now);
uint8_t cl_active(const cl_state *layers);
int cl_physical(
    cm_memory *memory,
    const ccd_writer *writer,
    const volatile uint8_t *keymap,
    uint8_t mac_mode,
    uint8_t position,
    uint8_t down,
    uint32_t now,
    uint16_t *out_code
);

#endif
