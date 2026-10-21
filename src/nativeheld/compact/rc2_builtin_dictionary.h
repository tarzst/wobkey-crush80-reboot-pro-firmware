#ifndef CRUSH80_RC2_BUILTIN_DICTIONARY_H
#define CRUSH80_RC2_BUILTIN_DICTIONARY_H

#include <stdint.h>

/* Raw (mask << 8) | usage, NOT QK_MODS. For the known direct builtin callers
 * of pinned RC2 7663f2fc...7d88 / TRNS 31722203...918b only.
 * Provenance and limits are in README.ru.md. This does not prove that there
 * are no indirect callers; unknown sources/actions must be rejected, not
 * silently assigned an existing identity or passed to a second writer.
 */
enum { CCH_RC2_BUILTIN_COUNT = 18 };
static const uint16_t cch_rc2_builtin_dictionary[CCH_RC2_BUILTIN_COUNT] = {
    0x0026, 0x0027, 0x0028, 0x0029, 0x002c, 0x0035, 0x0039, 0x0047, 0x0053,
    0x0100, 0x0200, 0x0226, 0x0400, 0x1000, 0x2000, 0x2026, 0x2027, 0x4000
};

#endif
