/* Standard RISC-V M-mode ABI. No Andes-only instructions or global RAM. */
    .option norelax
    .text
    .align 2
    .globl vci_enter
    .type vci_enter, @function
vci_enter:
    csrrci a0, mstatus, 8
    andi a0, a0, 8
    ret
    .size vci_enter, .-vci_enter

    .globl vci_leave
    .type vci_leave, @function
vci_leave:
    beqz a0, .Ldisabled
    csrsi mstatus, 8
    ret
.Ldisabled:
    csrci mstatus, 8
    ret
    .size vci_leave, .-vci_leave
    .section .note.GNU-stack,"",@progbits
