/* GCC may lower aggregate assignment/initialization to memcpy/memset even
 * with -ffreestanding. Supply their standard contracts for the RV32 build.
 * This is private to the test/core link, never a call into stock firmware.
 */
#include <stddef.h>

void *memcpy(void *restrict destination, const void *restrict source, size_t count)
{
    unsigned char *out = destination;
    const unsigned char *in = source;
    for (size_t i = 0; i < count; ++i) {
        out[i] = in[i];
    }
    return destination;
}

void *memset(void *destination, int value, size_t count)
{
    unsigned char *out = destination;
    for (size_t i = 0; i < count; ++i) {
        out[i] = (unsigned char)value;
    }
    return destination;
}
