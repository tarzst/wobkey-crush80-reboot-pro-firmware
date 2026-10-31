OUTPUT_ARCH(riscv)
ENTRY(cdb_hook_physical)
SECTIONS {
  . = 0x2000cccc;
  .text.cdb_hook_reset_common ALIGN(2) : { *(.text.cdb_hook_reset_common) }
  .text.cdb_hook_ready ALIGN(2) : { *(.text.cdb_hook_ready) }
  .text.cm_cancel.constprop.0.isra.0 ALIGN(2) : { *(.text.cm_cancel.constprop.0.isra.0) }
  ASSERT(. <= 0x2000cd32, "replacement region 0 overflow")
  . = 0x2000da08;
  .text.irq_guard ALIGN(4) : { *(.text) }
  ASSERT(. <= 0x2000da20, "replacement region 1 overflow")
  . = 0x2000da54;
  .text.cdb_reset_end ALIGN(2) : { *(.text.cdb_reset_end) }
  .text.cm_init.part.0.constprop.0.isra.0 ALIGN(2) : { *(.text.cm_init.part.0.constprop.0.isra.0) }
  ASSERT(. <= 0x2000dad0, "replacement region 2 overflow")
  . = 0x2000db0c;
  .text.ccd_synthetic.constprop.0 ALIGN(2) : { *(.text.ccd_synthetic.constprop.0) }
  .text.cdb_physical ALIGN(2) : { *(.text.cdb_physical) }
  .text.cdb_ready ALIGN(2) : { *(.text.cdb_ready) }
  .text.cdb_synthetic ALIGN(2) : { *(.text.cdb_synthetic) }
  .text.cm_step.constprop.0 ALIGN(2) : { *(.text.cm_step.constprop.0) }
  .text.reset ALIGN(2) : { *(.text.reset) }
  .text.update ALIGN(2) : { *(.text.update) }
  ASSERT(. <= 0x2000e75a, "replacement region 3 overflow")
  . = 0x20012c28;
  .rodata.actions.0 ALIGN(4) : { *(.rodata.actions.0) }
  .text.cdb_macro_chunk ALIGN(2) : { *(.text.cdb_macro_chunk) }
  ASSERT(. <= 0x20012f14, "replacement region 4 overflow")
  . = 0x2001326c;
  .text.cdb_hook_synthetic ALIGN(2) : { *(.text.cdb_hook_synthetic) }
  ASSERT(. <= 0x2001327e, "replacement region 5 overflow")
  . = 0x200133c0;
  .rodata.characters.1 ALIGN(4) : { *(.rodata.characters.1) }
  .text.enabled ALIGN(2) : { *(.text.enabled) }
  ASSERT(. <= 0x20013404, "replacement region 6 overflow")
  . = 0x2001342c;
  .text.cdb_oem_common ALIGN(2) : { *(.text.cdb_oem_common) }
  ASSERT(. <= 0x2001343c, "replacement region 7 overflow")
  . = 0x20013618;
  .text.cdb_hook_via ALIGN(2) : { *(.text.cdb_hook_via) }
  ASSERT(. <= 0x20013624, "replacement region 8 overflow")
  . = 0x200136dc;
  .text.clear ALIGN(2) : { *(.text.clear) }
  ASSERT(. <= 0x200136f4, "replacement region 9 overflow")
  . = 0x20013748;
  .text.ccd_macro_action ALIGN(2) : { *(.text.ccd_macro_action) }
  .text.cdb_macro_empty ALIGN(2) : { *(.text.cdb_macro_empty) }
  .text.cdb_reset_common ALIGN(2) : { *(.text.cdb_reset_common) }
  .text.keyboard ALIGN(2) : { *(.text.keyboard) }
  ASSERT(. <= 0x20013940, "replacement region 10 overflow")
  . = 0x200139c0;
  .text.cdb_reset_begin ALIGN(2) : { *(.text.cdb_reset_begin) }
  .text.emit ALIGN(2) : { *(.text.emit) }
  ASSERT(. <= 0x20013a30, "replacement region 11 overflow")
  . = 0x20013df8;
  .text.cdb_macro_poll ALIGN(2) : { *(.text.cdb_macro_poll) }
  .text.cdb_via_packet ALIGN(2) : { *(.text.cdb_via_packet) }
  .text.keymap_write ALIGN(2) : { *(.text.keymap_write) }
  .text.take_macro_request ALIGN(2) : { *(.text.take_macro_request) }
  ASSERT(. <= 0x200144c2, "replacement region 12 overflow")
  . = 0x2001bd70;
  .rodata.cch_rc2_builtin_dictionary ALIGN(4) : { *(.rodata.cch_rc2_builtin_dictionary) }
  .text.cdb_hook_physical ALIGN(2) : { *(.text.cdb_hook_physical) }
  ASSERT(. <= 0x2001bdc8, "replacement region 13 overflow")
  . = 0x2001be68;
  .text.apply.constprop.0 ALIGN(2) : { *(.text.apply.constprop.0) }
  .text.cch_decode ALIGN(2) : { *(.text.cch_decode) }
  .text.cdb_macro_scan ALIGN(2) : { *(.text.cdb_macro_scan) }
  ASSERT(. <= 0x2001c058, "replacement region 14 overflow")
  . = 0x2001c088;
  .text.cdb_reset_finish ALIGN(2) : { *(.text.cdb_reset_finish) }
  .text.keymap_read ALIGN(2) : { *(.text.keymap_read) }
  ASSERT(. <= 0x2001c1a0, "replacement region 15 overflow")
  . = 0x2001c220;
  .rodata.callers.0 ALIGN(4) : { *(.rodata.callers.0) }
  .rodata.cdb_via_packet ALIGN(4) : { *(.rodata.cdb_via_packet) }
  .text.cdb_restore_return ALIGN(2) : { *(.text.cdb_restore_return) }
  .text.cdb_save_callers ALIGN(2) : { *(.text.cdb_save_callers) }
  ASSERT(. <= 0x2001c2d8, "replacement region 16 overflow")
  .forbidden 0 : { *(.data .data.* .sdata .sdata.* .bss .bss.* .sbss .sbss.* COMMON)
    *(.got .got.* .iplt .rela.*) }
  ASSERT(SIZEOF(.forbidden) == 0, "implicit RAM or unsupported dynamic allocation")
  /DISCARD/ : { *(.comment .riscv.attributes .note.GNU-stack) }
}
