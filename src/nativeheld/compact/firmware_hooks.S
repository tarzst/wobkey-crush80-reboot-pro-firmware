/* Binding prototype: these sections are not placed in a keyboard image.
 * Mid-function entries preserve all caller-saved integer registers. C follows
 * the RV32 integer ABI and preserves s0..s11, gp and tp. No floating ISA used.
 */
    .option relax

    .macro save_callers
    addi sp, sp, -64
    sw t0, 4(sp)
    jal t0, cdb_save_callers
    .endm

    .section .text.cdb_save_callers,"ax",@progbits
cdb_save_callers:
    sw ra, 0(sp)
    sw t1, 8(sp)
    sw t2, 12(sp)
    sw a0, 16(sp)
    sw a1, 20(sp)
    sw a2, 24(sp)
    sw a3, 28(sp)
    sw a4, 32(sp)
    sw a5, 36(sp)
    sw a6, 40(sp)
    sw a7, 44(sp)
    sw t3, 48(sp)
    sw t4, 52(sp)
    sw t5, 56(sp)
    sw t6, 60(sp)
    jr t0

    .macro restore_callers bytes=64
    lw ra, 0(sp)
    lw t0, 4(sp)
    lw t1, 8(sp)
    lw t2, 12(sp)
    lw a0, 16(sp)
    lw a1, 20(sp)
    lw a2, 24(sp)
    lw a3, 28(sp)
    lw a4, 32(sp)
    lw a5, 36(sp)
    lw a6, 40(sp)
    lw a7, 44(sp)
    lw t3, 48(sp)
    lw t4, 52(sp)
    lw t5, 56(sp)
    lw t6, 60(sp)
    addi sp, sp, \bytes
    .endm

    .section .text.cdb_restore_return,"ax",@progbits
cdb_restore_return:
    restore_callers
    ret

    .section .text.cdb_hook_physical,"ax",@progbits
    .global cdb_hook_physical
cdb_hook_physical:
    save_callers
    mv a0, sp
    mv a1, s0
    call cdb_physical
    bnez a0, .Lstock
    la t0, cdb_physical_handled
    sw t0, 0(sp)
    j cdb_restore_return
.Lstock:
    la t0, cdb_physical_stock
    sw t0, 0(sp)
    li t0, 7
    sw t0, 60(sp)
    j cdb_restore_return
    /* RA is dead after13268: the enclosing OEM dispatch restores it from
     * its own96-byte frame before its only return. The continuation stored
     * above therefore replaces a dead register, never its saved caller RA.
     * This is specific to the pinned dispatch; not a general mid-hook ABI.
     */

    .macro frame_hook name, target, continuation
    .section .text.\name,"ax",@progbits
    .global \name
\name:
    save_callers
    mv a0, sp
    call \target
    .ifc \continuation,return
    j cdb_restore_return
    .else
    restore_callers
    j \continuation
    .endif
    .endm

    frame_hook cdb_hook_synthetic, cdb_synthetic, return
    frame_hook cdb_hook_reset_common, cdb_reset_common, return

    .section .text.cdb_hook_via,"ax",@progbits
    .global cdb_hook_via
cdb_hook_via:
    mv a0, a2
    call cdb_via_packet
    j cdb_macro_response

    .section .text.cdb_hook_ready,"ax",@progbits
    .global cdb_hook_ready
cdb_hook_ready:
    save_callers
    mv a0, sp
    call cdb_ready
    lw t0, 16(sp)
    lw t1, 28(sp)
    sb t1, 0(t0)
    /* As in dispatch, the enclosing function has already saved RA and
     * restores it before returning. Other caller registers remain exact. */
    la t0, cdb_ready_continue
    sw t0, 0(sp)
    j cdb_restore_return

    .section .text.cdb_oem_common,"ax",@progbits
    .global cdb_oem_common
cdb_oem_common:
    lbu a4, 929(gp)
    j cdb_oem_common_continue

/* Scoped reset frame. All callers are pinned mid-function JAL patches whose
 * original RA is dead. OEM blocks inside the scope must have no SP-relative
 * accesses. Preserve the previous MIE bit on the stack, including nesting;
 * never hold this scope across flash or blocking transport calls.
 */
    .section .text.cdb_reset_begin,"ax",@progbits
    .global cdb_reset_begin
cdb_reset_begin:
    addi sp, sp, -16
    sw t0, 4(sp)
    csrrci t0, mstatus, 8
    sw t0, 0(sp)
    li t0, 0x2001aad0
    beq ra, t0, .Linline_matrix
    li t0, 0x20010c18
    beq ra, t0, .Lmatrix
    li a1, 8
    j .Lbegin_done
.Lmatrix:
    li a1, 21
    j .Lbegin_done
.Linline_matrix:
    li a5, 0x81b10
.Lbegin_done:
    lw t0, 4(sp)
    ret

    .section .text.cdb_reset_end,"ax",@progbits
    .global cdb_reset_end
cdb_reset_end:
    save_callers
    mv a0, sp
    mv a1, s1
    mv a2, s0
    call cdb_reset_finish
    /* Reset is complete before MIE restoration. An IRQ from this point may
     * use the current stack normally: the saved caller frame remains owned
     * until restoration, exactly like a C epilogue after vci_leave(). */
    lw a0, 64(sp)
    andi a0, a0, 8
    call vci_leave
    restore_callers 80
    ret

    .section .note.GNU-stack,"",@progbits
