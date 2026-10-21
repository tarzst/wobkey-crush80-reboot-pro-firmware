#ifndef CRUSH80_DELTA_ADAPTER_H
#define CRUSH80_DELTA_ADAPTER_H

#include "compact_holds.h"
#include "../core/synthetic_binding.h"

typedef void (*ccd_emit)(void *context, uint8_t modifiers, uint8_t usage, uint8_t down);
typedef struct {
    const volatile uint8_t *basic;
    const volatile uint8_t *bitmap;
    ccd_emit emit;
    void *context;
    uint8_t overflow_enabled;
} ccd_writer;

/* Offline delta adapter: the caller owns initialized cch_state and the OEM
 * reports. All input producers, report writes and resets must be serialized.
 * The reports must represent exactly the union of these owners at entry.
 * The emitter is synchronous, cannot fail and must perform exactly the OEM
 * basic/bitmap update without re-entering this adapter. Readiness/suppression
 * guards must be checked before accepting an event and remain true until the
 * emitter returns. The emitter may modify reports, not owner state or writer.
 * No arguments may alias owners, event output or one another, except the
 * emitter's context may identify its external report buffers.
 * Overflow policy is fixed for the epoch. Reset requires the caller to clear
 * OEM reports and cch_reset together; startup/IRQ/RAM ownership are not bound.
 */
vck_result ccd_physical(cch_state *state, const ccd_writer *writer,
                        uint16_t position, uint8_t down, uint16_t code, cch_event *out);
vck_result ccd_synthetic(cch_state *state, const ccd_writer *writer,
                         uint16_t source, uint8_t down, vck_action action);
/* Atomic change of a macro action (possibly modifier bits + one usage).
 * A temporary tap must pass only its newly introduced components on release.
 * This does not create additional identities beyond the existing macro set.
 */
vck_result ccd_macro_action(cch_state *state, const ccd_writer *writer,
                            uint8_t down, vck_action action);

#endif
