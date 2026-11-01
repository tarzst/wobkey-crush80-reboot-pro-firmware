#ifndef CRUSH80_OEM_B91_H
#define CRUSH80_OEM_B91_H

/*
 * Hardware and OEM firmware memory map for WOBKEY Crush 80 Reboot Pro RGB
 * (Telink TLSR9511 / B91, base firmware V0108 + MacLayers RC2).
 *
 * The stock firmware anchors global state at GP = 0x80800 in DLM SRAM.
 */

#include <stdint.h>

#ifndef OEM_GP_ADDR
#define OEM_GP_ADDR               0x80800u
#endif
#define OEM_BYTE_AT(address)      ((volatile uint8_t *)(uintptr_t)(address))
#define OEM_HALF_AT(address)      ((volatile uint16_t *)(uintptr_t)(address))
#define OEM_WORD_AT(address)      ((volatile uint32_t *)(uintptr_t)(address))
#define OEM_GP_BYTE(offset)       OEM_BYTE_AT(OEM_GP_ADDR + (uintptr_t)(offset))
#define OEM_GP_HALF(offset)       OEM_HALF_AT(OEM_GP_ADDR + (uintptr_t)(offset))
#define OEM_TIMER_TICK_REG        0x80140200u /* 16 MHz system timer tick counter */
#define OEM_WD_CTRL2_REG          0x80140142u /* reg_tmr_ctrl2: bit 7 (0x80) = FLD_TMR_WD_EN */
#define OEM_WD_STATUS_REG         0x80140143u /* reg_tmr_sta: 0x0C clears WD status & counter */
#define OEM_WD_TARGET_REG         0x8014014cu /* reg_wt_target: 32-bit PCLK cycle target */
#define OEM_WD_ENABLE_BIT         0x80u
#define OEM_WD_CLEAR_MASK         0x0cu
#define OEM_WD_TARGET_4S          0x0b700000u /* ~4.0 s at 48 MHz PCLK ((732 << 18)) */

/* DLM SRAM offsets relative to GP (0x80800). */
enum {
    OEM_KEYMAP_NEG_OFFSET     = 1536,  /* GP - 1536 (0x80200): 1024-byte big-endian keymap cache */
    OEM_CONFIG_OFFSET         = 104,   /* 0x80868: 64-byte runtime configuration block */
    OEM_NKRO_OFFSET           = 124,   /* 0x8087C: non-zero when NKRO bitmap overflow is enabled */
    OEM_DEBOUNCE_OFFSET       = 133,   /* 0x80885: config[29] 0x00 = main-loop debounce, 0xFF = ISR debounce */
    OEM_PROTOCOL_VER_OFFSET   = 135,   /* 0x80887: active VIA protocol version (9 or 11) */
    OEM_LAYER_SLOT_OFFSET     = 380,   /* 0x8097C: uint16_t[4] active flash slot offsets for layers 0..3 */
    OEM_MACRO_UPLOAD_OFFSET   = 390,   /* 0x80986: uint16_t macro staging upload state/high-water mark */
    OEM_MACRO_ID_OFFSET       = 392,   /* 0x80988: uint8_t requested macro index (0..15) */
    OEM_MACRO_TIMER_OFFSET    = 394,   /* 0x8098A: uint16_t stock macro delay counter */
    OEM_MACRO_SLOT_OFFSET     = 396,   /* 0x8098C: uint16_t active macro flash slot offset in 0x89000 */
    OEM_POSITION_OFFSET       = 560,   /* 0x80A30: uint8_t current matrix position (row * 16 + col) */
    OEM_PRESSED_OFFSET        = 562,   /* 0x80A32: uint8_t key state (0xFF = pressed, 0x00 = released) */
    OEM_CONSUMER_OFFSET       = 792,   /* 0x80B18: 3-byte consumer report buffer */
    OEM_STATUS_OFFSET         = 804,   /* 0x80B24: dirty report bits (0x02=6KRO, 0x04=NKRO, 0x08=Cons, 0x10=Sys, 0x40=suppress) */
    OEM_STATUS2_OFFSET        = 805,   /* 0x80B25: extra status bits (0x04=flash save, 0x20=macro, 0x40=mouse) */
    OEM_VIA_FLAGS_OFFSET      = 812,   /* 0x80B2C: VIA handshake/state flags */
    OEM_MACRO_FLAGS_OFFSET    = 813,   /* 0x80B2D: macro runtime flags (bit 2=request, bit 3=busy, bit 7=builtin) */
    OEM_SAVE_FLAGS_OFFSET     = 814,   /* 0x80B2E: deferred flash save trigger flags */
    OEM_BASIC_OFFSET          = 848,   /* 0x80B50: 8-byte 6KRO keyboard report buffer */
    OEM_MOUSE_OFFSET          = 860,   /* 0x80B5C: 8-byte mouse report buffer */
    OEM_MOUSE_TAIL_OFFSET     = 868,   /* 0x80B64: address returned in a0/a1 by stock common reset */
    OEM_SYSTEM_OFFSET         = 912,   /* 0x80B90: 3-byte system control report buffer */
    OEM_SAVE_COUNTER_OFFSET   = 917,   /* 0x80B95: deferred save countdown timer */
    OEM_READY_OFFSET          = 929,   /* 0x80BA1: startup readiness counter (active when > 7) */
    OEM_VIA_STATE_OFFSET      = 964,   /* 0x80BC4: 30-byte VIA state snapshot */
    OEM_VIA_PENDING_OFFSET    = 979,   /* 0x80BD3: VIA pending state bits */
    OEM_STAGING_OFFSET        = 1508,  /* 0x80DE4: 512-byte macro staging buffer */
    OEM_BITMAP_OFFSET         = 4840   /* 0x81AE8: 16-byte NKRO bitmap report buffer */
};

/* B91 XIP flash layout constants. */
#define OEM_KEYMAP_FLASH_BASE     0x84000u /* 4 sectors (0x84000..0x87FFF), 16 x 256B slots per layer */
#define OEM_MACRO_FLASH_BASE      0x89000u /* 1 sector (0x89000..0x89FFF), 8 x 512B slots */
#define OEM_FLASH_SECTOR_BYTES    4096u
#define OEM_KEYMAP_LAYER_BYTES    256u

#endif
