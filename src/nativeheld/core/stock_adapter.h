#ifndef CRUSH80_STOCK_ADAPTER_H
#define CRUSH80_STOCK_ADAPTER_H

#define VCA_RESET_REPORTS_VALUE 0
#define VCA_RESET_MATRIX_VALUE 1
#ifndef __ASSEMBLER__
#include "stock_reports.h"

enum { VCA_NONE = 0, VCA_KEYBOARD = 1, VCA_STOCK = 2 };

/* Dispatch result, also used as the physical assignment latched to release.
 * STOCK must be passed to the OEM dispatcher with its original side effects;
 * its keyboard contributions must enter vca_synthetic before each OEM send.
 * NONE suppresses duplicate/unmatched physical events.
 */
typedef struct {
    uint16_t code;
    uint8_t layer;
    uint8_t kind;
} vca_event;

typedef struct {
    vck_state core;
    vca_event physical[VCK_POSITIONS];
    vcs_reports reports;
    uint8_t pending;
    uint8_t overflow_enabled;
} vca_state;

/* This module is the C boundary for future assembly hooks. It has no fixed
 * RAM address, source allocator, interrupt controls, or transport calls.
 * Calls, storage and publishing must be serialized with stock producers and
 * consumers. Buffers/outputs must not alias state, holds, keymap or each other.
 * State/holds must be initialized here and not externally mutated.
 */
vck_result vca_init(vca_state *state, vck_hold *holds, uint16_t capacity,
                    uint8_t overflow_enabled);
vck_result vca_reset(vca_state *state);
typedef enum {
    VCA_RESET_REPORTS = VCA_RESET_REPORTS_VALUE,
    VCA_RESET_MATRIX = VCA_RESET_MATRIX_VALUE,
} vca_reset_scope;
/* Accept a complete OEM keyboard reset that already owns host notification.
 * Clears every keyboard owner, writes canonical empty keyboard buffers and drops
 * local pending. Does not set/clear stock dirty bits or send anything. This is
 * not a partial release or a substitute for vca_reset + vca_publish. Caller
 * REPORTS retains STOCK physical assignments until release, so OEM Fn/builtin
 * cleanup still receives its original code. MATRIX also clears those latches;
 * only use it after OEM clears its matrix and associated side-effect state.
 * Caller must serialize the entire OEM reset with all producers/consumers.
 * Invalid arguments leave state, holds and both buffers unchanged.
 */
vck_result vca_accept_stock_reset(vca_state *state, volatile uint8_t *basic,
                                  volatile uint8_t *bitmap, vca_reset_scope scope);
vck_result vca_press(vca_state *state, uint16_t position,
                     const uint8_t *keymap, size_t keymap_bytes,
                     const uint8_t *order, size_t order_count, vca_event *out);
vck_result vca_release(vca_state *state, uint16_t position, vca_event *out);
/* source >= 128 is the identity of one independent builtin/macro hold. The
 * caller must establish its lifetime; keycodes/callsites alone are not IDs.
 * A repeated press is latched; release ignores action and removes only source.
 * On failure there is no change to owners, reports, pending flags or outputs.
 */
vck_result vca_synthetic(vca_state *state, uint16_t source, uint8_t pressed,
                         vck_action action);
/* Copies complete changed reports, ORs only pending keyboard bits into stock
 * status, then clears local pending. No send/ack and no consumer/system reset.
 * Stock addresses are supplied by the independently verified hook layer.
 */
vck_result vca_publish(vca_state *state, volatile uint8_t *basic,
                       volatile uint8_t *bitmap, volatile uint8_t *status);

#endif /* !__ASSEMBLER__ */
#endif
