#ifndef CRUSH80_STOCK_REPORTS_H
#define CRUSH80_STOCK_REPORTS_H

#include "via_core.h"

enum {
    VCS_BASIC_BYTES = 8,
    VCS_BITMAP_BYTES = 16,
    VCS_BITMAP_MAX = 0x70,
    VCS_DIRTY_BASIC = 2, /* stock gp+804 bit 1 */
    VCS_DIRTY_BITMAP = 4 /* stock gp+804 bit 2 */
};

/* Owns aggregate usage placement, independent of individual source owners.
 * No promotion from bitmap into a newly freed basic slot while held.
 * Storage belongs to caller; only these functions may change it.
 */
typedef struct {
    uint8_t basic[VCS_BASIC_BYTES];
    uint8_t bitmap[VCS_BITMAP_BYTES];
} vcs_reports;

_Static_assert(sizeof(vcs_reports) == 24, "stock report storage changed");

vck_result vcs_reset(vcs_reports *reports);
/* Atomic on failure: reports and dirty are unchanged. New usages fill basic
 * holes, then bitmap if enabled and within its declared descriptor range.
 * No silent drop or out-of-range bitmap write. overflow_enabled must be 0/1.
 */
vck_result vcs_reconcile(vcs_reports *reports, const vck_report *desired,
                         uint8_t overflow_enabled, uint8_t *dirty);

#endif
