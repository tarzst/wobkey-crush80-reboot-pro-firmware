#ifndef CRUSH80_PHYSICAL_BINDING_H
#define CRUSH80_PHYSICAL_BINDING_H

#include "stock_adapter.h"

/* Caller-owned stock view. All calls and snapshots must be serialized with
 * stock event producers, VIA writes and report consumers. No pointer may
 * alias adapter storage, the saved frame or any other view member.
 * Hardware addresses and RAM ownership are deliberately outside this API.
 */
typedef struct {
    const uint8_t *keymap;
    size_t keymap_bytes;
    const volatile uint8_t *primary;
    const volatile uint8_t *mac;
    const volatile uint16_t *overlay;
    const volatile uint8_t *pressed;
    volatile uint8_t *status;
    volatile uint8_t *basic;
    volatile uint8_t *bitmap;
} vcp_stock_view;

typedef struct {
    uint8_t primary;
    uint8_t mac;
    uint16_t overlay;
    uint8_t status;
} vcp_layers;

/* RV32 integer register file captured at file 0x13268. x[8] is s0: physical
 * position before stock advances it. Only a1/a3 may be changed, and only for
 * a successful STOCK dispatch. sp is observational, not callback-controlled.
 */
typedef struct { uint32_t x[32]; } vcp_frame;
_Static_assert(sizeof(vcp_frame) == 128, "hook register frame changed");

enum { VCP_HANDLED = 0, VCP_OEM = 1 };

/* RC2 primary Mac remapping, optional active overlay, then primary and its
 * paired base when primary is odd. Explicit cross-family overlays remain
 * explicit. Unsupported selectors return an error, never wrap to layer 0.
 * On failure outputs are unchanged. order has room for three entries.
 */
vck_result vcp_layer_order(vcp_layers layers, uint8_t order[3], uint8_t *count);

/* Uses the adapter's latch for release: no layout/selector read on release.
 * On success publishes pending reports before returning the dispatch route.
 * Return VCP_HANDLED/VCP_OEM, or a negative vck_result on rejection. There is
 * no OEM fallback on rejection: it would bypass the shared ownership model.
 * Stock readiness/suppression, resets and synthetic writers must be bound
 * before this function can be connected to a keyboard image.
 */
int vcp_apply(vca_state *state, const vcp_stock_view *view, vcp_frame *frame);

#endif
