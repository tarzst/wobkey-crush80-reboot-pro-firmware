#ifndef CRUSH80_FIRMWARE_BINDING_H
#define CRUSH80_FIRMWARE_BINDING_H

#include "macro_stream.h"

/* Target binding between stock Crush 80 RGB RC2 paths and the compact
 * 512-byte NativeHeld workspace. The linker supplies absolute symbols;
 * no implicit .bss or .data sections are emitted. */
typedef struct {
    uint32_t ra, t0, t1, t2;
    uint32_t a[8];
    uint32_t t3, t4, t5, t6;
} cdb_frame;
_Static_assert(sizeof(cdb_frame) == 64 && offsetof(cdb_frame, a) == 16,
               "caller frame ABI changed");

extern cm_memory cdb_workspace;
extern void cdb_oem_common(uint8_t modifiers, uint8_t usage);
extern void cdb_oem_send(void);
extern void cdb_flash_read(uint32_t address, uint32_t length, uint8_t *destination);
extern int cdb_flash_program(uint32_t address, uint32_t length, const uint8_t *source);
extern void cdb_flash_erase(uint32_t address);
extern void cdb_rgb_changed(void);
extern const uint8_t cdb_palette[];
extern const uint8_t cdb_brightness_table[];
extern uint32_t vci_enter(void);
extern void vci_leave(uint32_t saved);

int cdb_physical(cdb_frame *frame, uint32_t position);
void cdb_synthetic(cdb_frame *frame);
void cdb_ready(cdb_frame *frame);
void cdb_reset_common(cdb_frame *frame);
void cdb_reset_finish(cdb_frame *frame, uint32_t s1, uint32_t s0);
void cdb_macro_poll(void);
int32_t cdb_macro_scan(uint32_t address, uint8_t *unused, uint32_t length);
int cdb_macro_empty(uint32_t address, uint32_t length, const uint8_t *unused);
void cdb_macro_chunk(uint8_t packet[32]);
void cdb_via_packet(uint8_t packet[32]);

#endif
