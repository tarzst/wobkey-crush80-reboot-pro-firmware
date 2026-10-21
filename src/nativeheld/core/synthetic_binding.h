#ifndef CRUSH80_SYNTHETIC_BINDING_H
#define CRUSH80_SYNTHETIC_BINDING_H

#include "physical_binding.h"

enum {
    VCSYN_BUILTIN_BASE = VCK_POSITIONS,
    VCSYN_MACRO_MOD_BASE = VCK_POSITIONS * 2,
    VCSYN_MACRO_USAGE_BASE = VCSYN_MACRO_MOD_BASE + 8,
    VCSYN_CAPACITY = VCSYN_MACRO_USAGE_BASE + VCK_USAGE_MAX - VCK_USAGE_MIN + 1,
    VCSYN_NO_SOURCE = 65535
};

typedef struct {
    const vcp_stock_view *keyboard;
    const volatile uint8_t *position;
    const volatile uint8_t *readiness;
} vcsyn_stock_view;

/* Pinned common-writer callers only. Builtins use one source per physical
 * position: primary release completes before the secondary pulse begins.
 * The single stock macro engine has separate slots for each modifier/usage;
 * a repeated down is idempotent and up removes only that macro contribution.
 * Macro classification does not use the stale last physical position.
 * Unknown callers/actions fail without assigning a guessed identity.
 */
vck_result vcsyn_owner(uint32_t return_address, uint16_t position,
                       vck_action action, uint16_t *source);

/* Mirrors stock readiness/suppression guards before examining action args.
 * On success publishes before the caller's next immediate send. The original
 * common writer must not run afterward. frame is never modified.
 * Ownership reset on suppression, disconnect, OS change and macro cleanup
 * must still be integrated; these functions alone are not firmware-ready.
 */
int vcsyn_apply(vca_state *state, const vcsyn_stock_view *view, const vcp_frame *frame);

#endif
