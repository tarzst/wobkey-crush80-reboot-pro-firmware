"""RV32IMC + used XAndesPerf/DSP subset interpreter for pinned Crush80 images.

Independent of the capstone-based listings: every encoding is decoded here
from the RISC-V base specification and from the pinned `andes.td` field
layouts.  Anything not implemented raises `Unsupported`; nothing is ever
treated as a NOP.  Only integer state, the F register file as raw 32-bit
values (loads/stores only) and a plain CSR map are modelled.

Interpretation, not taken from andes.td (which has no semantics for it):
BFOZ/BFOS with msb < lsb is the insert form rd[lsb:msb] = rs1[lsb-msb:0].
A first reading (rs1[msb:0] << lsb) was refuted by execution: the RC2 row
loop at 0x2001329a uses `bfoz s7, s7, 1, 7` as "s7 = (s7 << 1) & 0xff", and
with the wrong reading the loop never visits a row.  The other 23 instances
(e.g. `bfoz a2, a2, 8, 15` = byte << 8) are consistent with this reading.
"""

MASK = 0xFFFFFFFF
REG_NAMES = ('zero ra sp gp tp t0 t1 t2 s0 s1 a0 a1 a2 a3 a4 a5 a6 a7 '
             's2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6').split()


class Unsupported(Exception):
    pass


def sext(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def bits(word, hi, lo):
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


def s32(value):
    return sext(value, 32)


# ---------------------------------------------------------------- decoding
# A decoded instruction is (op, rd, rs1, rs2, imm, size, extra).

def decode32(w):
    opcode = w & 0x7F
    rd, f3, rs1, rs2, f7 = bits(w, 11, 7), bits(w, 14, 12), bits(w, 19, 15), bits(w, 24, 20), w >> 25
    i_imm = sext(w >> 20, 12)
    s_imm = sext((f7 << 5) | rd, 12)
    b_imm = sext((bits(w, 31, 31) << 12) | (bits(w, 7, 7) << 11) |
                 (bits(w, 30, 25) << 5) | (bits(w, 11, 8) << 1), 13)
    if opcode == 0x37:
        return ('lui', rd, 0, 0, s32(w & 0xFFFFF000), 4, None)
    if opcode == 0x17:
        return ('auipc', rd, 0, 0, s32(w & 0xFFFFF000), 4, None)
    if opcode == 0x6F:
        imm = sext((bits(w, 31, 31) << 20) | (bits(w, 19, 12) << 12) |
                   (bits(w, 20, 20) << 11) | (bits(w, 30, 21) << 1), 21)
        return ('jal', rd, 0, 0, imm, 4, None)
    if opcode == 0x67 and f3 == 0:
        return ('jalr', rd, rs1, 0, i_imm, 4, None)
    if opcode == 0x63:
        name = {0: 'beq', 1: 'bne', 4: 'blt', 5: 'bge', 6: 'bltu', 7: 'bgeu'}.get(f3)
        if name:
            return (name, 0, rs1, rs2, b_imm, 4, None)
    if opcode == 0x03:
        name = {0: 'lb', 1: 'lh', 2: 'lw', 4: 'lbu', 5: 'lhu'}.get(f3)
        if name:
            return (name, rd, rs1, 0, i_imm, 4, None)
    if opcode == 0x23:
        name = {0: 'sb', 1: 'sh', 2: 'sw'}.get(f3)
        if name:
            return (name, 0, rs1, rs2, s_imm, 4, None)
    if opcode == 0x07 and f3 == 2:
        return ('flw', rd, rs1, 0, i_imm, 4, None)
    if opcode == 0x27 and f3 == 2:
        return ('fsw', 0, rs1, rs2, s_imm, 4, None)
    if opcode == 0x13:
        if f3 == 1 and f7 == 0:
            return ('slli', rd, rs1, 0, rs2, 4, None)
        if f3 == 5 and f7 == 0:
            return ('srli', rd, rs1, 0, rs2, 4, None)
        if f3 == 5 and f7 == 0x20:
            return ('srai', rd, rs1, 0, rs2, 4, None)
        name = {0: 'addi', 2: 'slti', 3: 'sltiu', 4: 'xori', 6: 'ori', 7: 'andi'}.get(f3)
        if name:
            return (name, rd, rs1, 0, i_imm, 4, None)
    if opcode == 0x33:
        table = {
            (0, 0): 'add', (0x20, 0): 'sub', (0, 1): 'sll', (0, 2): 'slt',
            (0, 3): 'sltu', (0, 4): 'xor', (0, 5): 'srl', (0x20, 5): 'sra',
            (0, 6): 'or', (0, 7): 'and',
            (1, 0): 'mul', (1, 1): 'mulh', (1, 2): 'mulhsu', (1, 3): 'mulhu',
            (1, 4): 'div', (1, 5): 'divu', (1, 6): 'rem', (1, 7): 'remu'}
        name = table.get((f7, f3))
        if name:
            return (name, rd, rs1, rs2, 0, 4, None)
    if opcode == 0x0F and f3 in (0, 1):
        return ('fence', 0, 0, 0, 0, 4, None)
    if opcode == 0x73:
        if w == 0x30200073:
            return ('mret', 0, 0, 0, 0, 4, None)
        if w == 0x10500073:
            return ('wfi', 0, 0, 0, 0, 4, None)
        if f3 in (1, 2, 3, 5, 6, 7):
            name = {1: 'csrrw', 2: 'csrrs', 3: 'csrrc', 5: 'csrrwi', 6: 'csrrsi', 7: 'csrrci'}[f3]
            return (name, rd, rs1, 0, w >> 20, 4, None)
    if opcode == 0x0B:                       # custom-0: GP byte access
        imm = sext((bits(w, 31, 31) << 17) | (bits(w, 16, 15) << 15) |
                   (bits(w, 19, 17) << 12) | (bits(w, 20, 20) << 11) |
                   (bits(w, 30, 21) << 1) | bits(w, 14, 14), 18)
        f2 = bits(w, 13, 12)
        if f2 == 3:
            imm = sext((bits(w, 31, 31) << 17) | (bits(w, 16, 15) << 15) |
                       (bits(w, 19, 17) << 12) | (bits(w, 7, 7) << 11) |
                       (bits(w, 30, 25) << 5) | (bits(w, 11, 8) << 1) |
                       bits(w, 14, 14), 18)
            return ('sbgp', 0, 0, rs2, imm, 4, None)
        return (('lbgp', 'addigp', 'lbugp')[f2], rd, 0, 0, imm, 4, None)
    if opcode == 0x2B:                       # custom-1: GP half/word access
        if f3 in (1, 5):
            imm = sext((bits(w, 31, 31) << 16) | (bits(w, 16, 15) << 14) |
                       (bits(w, 19, 17) << 11) | (bits(w, 20, 20) << 10) |
                       bits(w, 30, 21), 17) << 1
            return ('lhgp' if f3 == 1 else 'lhugp', rd, 0, 0, imm, 4, None)
        if f3 == 2:
            imm = sext((bits(w, 31, 31) << 16) | (bits(w, 21, 21) << 15) |
                       (bits(w, 16, 15) << 13) | (bits(w, 19, 17) << 10) |
                       (bits(w, 20, 20) << 9) | bits(w, 30, 22), 17) << 2
            return ('lwgp', rd, 0, 0, imm, 4, None)
        if f3 == 0:
            imm = sext((bits(w, 31, 31) << 16) | (bits(w, 16, 15) << 14) |
                       (bits(w, 19, 17) << 11) | (bits(w, 7, 7) << 10) |
                       (bits(w, 30, 25) << 4) | bits(w, 11, 8), 17) << 1
            return ('shgp', 0, 0, rs2, imm, 4, None)
        if f3 == 4:
            imm = sext((bits(w, 31, 31) << 16) | (bits(w, 8, 8) << 15) |
                       (bits(w, 16, 15) << 13) | (bits(w, 19, 17) << 10) |
                       (bits(w, 7, 7) << 9) | (bits(w, 30, 25) << 3) |
                       bits(w, 11, 9), 17) << 2
            return ('swgp', 0, 0, rs2, imm, 4, None)
    if opcode == 0x5B:                       # custom-2
        imm10 = sext((bits(w, 31, 31) << 9) | (bits(w, 29, 25) << 4) | bits(w, 11, 8), 10) << 1
        if f3 == 7:
            cimm = (bits(w, 7, 7) << 5) | rs2
            return ('bbs' if bits(w, 30, 30) else 'bbc', 0, rs1, 0, imm10, 4, cimm)
        if f3 in (5, 6):
            cimm = (bits(w, 30, 30) << 6) | (bits(w, 7, 7) << 5) | rs2
            return ('beqc' if f3 == 5 else 'bnec', 0, rs1, 0, imm10, 4, cimm)
        if f3 in (2, 3):
            msb, lsb = bits(w, 31, 26), bits(w, 25, 20)
            if msb >= 32 or lsb >= 32:
                raise Unsupported(f'RV64 bitfield {w:#010x}')
            return ('bfoz' if f3 == 2 else 'bfos', rd, rs1, 0, 0, 4, (msb, lsb))
        if f3 == 0:
            shift = {5: 1, 6: 2, 7: 3}.get(f7)
            if shift:
                return ('lea', rd, rs1, rs2, shift, 4, None)
    if opcode == 0x7F:                       # custom-3: Andes DSP subset
        # Encoding from pinned andes-riscv-opc.h MATCH/MASK_SWAP8.
        # Each 16-bit lane swaps its two bytes; this is not a full bswap32.
        if w & 0xFFF0707F == 0xAD80007F:
            return ('swap8', rd, rs1, 0, 0, 4, None)
        key = w & 0xFE00707F
        name = {0xC400107F: 'maddr32', 0xC600107F: 'msubr32', 0xF000007F: 'minw'}.get(key)
        if name:
            return (name, rd, rs1, rs2, 0, 4, None)
    raise Unsupported(f'32-bit encoding {w:#010x}')


def decode16(h):
    q, f3 = h & 3, h >> 13
    r = lambda value: 8 + value                       # compressed register
    rd_, rs2_ = r(bits(h, 4, 2)), r(bits(h, 4, 2))
    rs1_ = r(bits(h, 9, 7))
    rd, rs2 = bits(h, 11, 7), bits(h, 6, 2)
    ci = sext((bits(h, 12, 12) << 5) | bits(h, 6, 2), 6)
    if h == 0:
        raise Unsupported('c.unimp')
    if q == 0:
        if f3 == 0:
            imm = (bits(h, 10, 7) << 6) | (bits(h, 12, 11) << 4) | (bits(h, 5, 5) << 3) | (bits(h, 6, 6) << 2)
            if imm == 0:
                raise Unsupported('reserved c.addi4spn')
            return ('addi', rd_, 2, 0, imm, 2, None)
        lw_imm = (bits(h, 5, 5) << 6) | (bits(h, 12, 10) << 3) | (bits(h, 6, 6) << 2)
        if f3 == 2:
            return ('lw', rd_, rs1_, 0, lw_imm, 2, None)
        if f3 == 3:
            return ('flw', rd_, rs1_, 0, lw_imm, 2, None)
        if f3 == 6:
            return ('sw', 0, rs1_, rs2_, lw_imm, 2, None)
        if f3 == 7:
            return ('fsw', 0, rs1_, rs2_, lw_imm, 2, None)
    if q == 1:
        if f3 == 0:
            return ('addi', rd, rd, 0, ci, 2, None)
        if f3 in (1, 5):
            imm = sext((bits(h, 12, 12) << 11) | (bits(h, 8, 8) << 10) | (bits(h, 10, 9) << 8) |
                       (bits(h, 6, 6) << 7) | (bits(h, 7, 7) << 6) | (bits(h, 2, 2) << 5) |
                       (bits(h, 11, 11) << 4) | (bits(h, 5, 3) << 1), 12)
            return ('jal', 1 if f3 == 1 else 0, 0, 0, imm, 2, None)
        if f3 == 2:
            return ('addi', rd, 0, 0, ci, 2, None)
        if f3 == 3:
            if rd == 2:
                imm = sext((bits(h, 12, 12) << 9) | (bits(h, 4, 3) << 7) | (bits(h, 5, 5) << 6) |
                           (bits(h, 2, 2) << 5) | (bits(h, 6, 6) << 4), 10)
                if imm == 0:
                    raise Unsupported('reserved c.addi16sp')
                return ('addi', 2, 2, 0, imm, 2, None)
            if ci == 0:
                raise Unsupported('reserved c.lui')
            return ('lui', rd, 0, 0, s32((ci << 12) & MASK), 2, None)
        if f3 == 4:
            f2 = bits(h, 11, 10)
            shamt = (bits(h, 12, 12) << 5) | bits(h, 6, 2)
            if f2 in (0, 1):
                if shamt >= 32:
                    raise Unsupported('RV64 compressed shift')
                return ('srli' if f2 == 0 else 'srai', rs1_, rs1_, 0, shamt, 2, None)
            if f2 == 2:
                return ('andi', rs1_, rs1_, 0, ci, 2, None)
            if bits(h, 12, 12) == 0:
                name = ('sub', 'xor', 'or', 'and')[bits(h, 6, 5)]
                return (name, rs1_, rs1_, rs2_, 0, 2, None)
        if f3 in (6, 7):
            imm = sext((bits(h, 12, 12) << 8) | (bits(h, 6, 5) << 6) | (bits(h, 2, 2) << 5) |
                       (bits(h, 11, 10) << 3) | (bits(h, 4, 3) << 1), 9)
            return ('beq' if f3 == 6 else 'bne', 0, rs1_, 0, imm, 2, None)
    if q == 2:
        if f3 == 0:
            shamt = (bits(h, 12, 12) << 5) | bits(h, 6, 2)
            if shamt >= 32:
                raise Unsupported('RV64 compressed shift')
            return ('slli', rd, rd, 0, shamt, 2, None)
        sp_lw = (bits(h, 3, 2) << 6) | (bits(h, 12, 12) << 5) | (bits(h, 6, 4) << 2)
        sp_sw = (bits(h, 8, 7) << 6) | (bits(h, 12, 9) << 2)
        if f3 == 2:
            if rd == 0:
                raise Unsupported('reserved c.lwsp')
            return ('lw', rd, 2, 0, sp_lw, 2, None)
        if f3 == 3:
            return ('flw', rd, 2, 0, sp_lw, 2, None)
        if f3 == 6:
            return ('sw', 0, 2, rs2, sp_sw, 2, None)
        if f3 == 7:
            return ('fsw', 0, 2, rs2, sp_sw, 2, None)
        if f3 == 4:
            if bits(h, 12, 12) == 0:
                if rs2 == 0:
                    if rd == 0:
                        raise Unsupported('reserved c.jr')
                    return ('jalr', 0, rd, 0, 0, 2, None)
                return ('add', rd, 0, rs2, 0, 2, None)
            if rs2 == 0:
                if rd == 0:
                    return ('ebreak', 0, 0, 0, 0, 2, None)
                return ('jalr', 1, rd, 0, 0, 2, None)
            return ('add', rd, rd, rs2, 0, 2, None)
    raise Unsupported(f'16-bit encoding {h:#06x}')


class Halt(Exception):
    """Raised by a hook or by reaching the return sentinel."""


class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.x = [0] * 32
        self.f = [0] * 32
        self.csr = {}
        self.pc = 0
        self.steps = 0
        self.total = 0
        self.min_sp = MASK
        self.cache = {}
        self.hooks = {}
        self.trace = None

    def fetch(self, pc):
        cached = self.cache.get(pc)
        if cached is None:
            half = self.bus.fetch16(pc)
            if half & 3 == 3:
                cached = decode32(half | (self.bus.fetch16(pc + 2) << 16))
            else:
                cached = decode16(half)
            self.cache[pc] = cached
        return cached

    def set(self, reg, value):
        if reg:
            self.x[reg] = value & MASK
            if reg == 2 and self.x[2] < self.min_sp:
                self.min_sp = self.x[2]

    def csr_rw(self, number, write, value=None):
        old = self.csr.get(number, 0)
        if write is not None:
            self.csr[number] = write(old) & MASK
        return old

    def run(self, limit):
        x, bus = self.x, self.bus
        while True:
            pc = self.pc
            hook = self.hooks.get(pc)
            if hook is not None:
                if hook(self) is not False:
                    continue
            if self.steps >= limit:
                raise RuntimeError(f'step limit {limit} reached at {pc:#x}')
            self.steps += 1
            self.total += 1
            op, rd, rs1, rs2, imm, size, extra = self.fetch(pc)
            if self.trace is not None:
                self.trace(self, pc, op)
            nxt = (pc + size) & MASK
            a, b = x[rs1], x[rs2]
            if op == 'addi':
                self.set(rd, a + imm)
            elif op == 'add':
                self.set(rd, a + b)
            elif op in ('lw', 'lb', 'lbu', 'lh', 'lhu'):
                addr = (a + imm) & MASK
                if op == 'lw':
                    value = bus.read(addr, 4, pc)
                elif op == 'lb':
                    value = sext(bus.read(addr, 1, pc), 8)
                elif op == 'lbu':
                    value = bus.read(addr, 1, pc)
                elif op == 'lh':
                    value = sext(bus.read(addr, 2, pc), 16)
                else:
                    value = bus.read(addr, 2, pc)
                self.set(rd, value)
            elif op in ('sw', 'sh', 'sb'):
                bus.write((a + imm) & MASK, {'sw': 4, 'sh': 2, 'sb': 1}[op], b, pc)
            elif op in ('lbgp', 'lbugp', 'addigp', 'lhgp', 'lhugp', 'lwgp'):
                addr = (x[3] + imm) & MASK
                if op == 'addigp':
                    self.set(rd, addr)
                elif op == 'lbgp':
                    self.set(rd, sext(bus.read(addr, 1, pc), 8))
                elif op == 'lbugp':
                    self.set(rd, bus.read(addr, 1, pc))
                elif op == 'lhgp':
                    self.set(rd, sext(bus.read(addr, 2, pc), 16))
                elif op == 'lhugp':
                    self.set(rd, bus.read(addr, 2, pc))
                else:
                    self.set(rd, bus.read(addr, 4, pc))
            elif op in ('sbgp', 'shgp', 'swgp'):
                bus.write((x[3] + imm) & MASK, {'sbgp': 1, 'shgp': 2, 'swgp': 4}[op], b, pc)
            elif op == 'lui':
                self.set(rd, imm)
            elif op == 'auipc':
                self.set(rd, pc + imm)
            elif op == 'jal':
                self.set(rd, nxt)
                nxt = (pc + imm) & MASK
            elif op == 'jalr':
                target = (a + imm) & ~1 & MASK
                self.set(rd, nxt)
                nxt = target
            elif op in ('beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu'):
                taken = {'beq': a == b, 'bne': a != b, 'blt': s32(a) < s32(b),
                         'bge': s32(a) >= s32(b), 'bltu': a < b, 'bgeu': a >= b}[op]
                if taken:
                    nxt = (pc + imm) & MASK
            elif op in ('bbc', 'bbs'):
                if ((a >> extra) & 1) == (op == 'bbs'):
                    nxt = (pc + imm) & MASK
            elif op in ('beqc', 'bnec'):
                if (a == extra) == (op == 'beqc'):
                    nxt = (pc + imm) & MASK
            elif op in ('andi', 'ori', 'xori'):
                self.set(rd, {'andi': a & imm, 'ori': a | imm, 'xori': a ^ imm}[op] & MASK)
            elif op in ('and', 'or', 'xor', 'sub'):
                self.set(rd, {'and': a & b, 'or': a | b, 'xor': a ^ b, 'sub': a - b}[op])
            elif op == 'slli':
                self.set(rd, a << imm)
            elif op == 'srli':
                self.set(rd, a >> imm)
            elif op == 'srai':
                self.set(rd, s32(a) >> imm)
            elif op in ('sll', 'srl', 'sra'):
                sh = b & 31
                self.set(rd, a << sh if op == 'sll' else a >> sh if op == 'srl' else s32(a) >> sh)
            elif op in ('slti', 'sltiu', 'slt', 'sltu'):
                if op == 'slti':
                    value = s32(a) < imm
                elif op == 'sltiu':
                    value = a < (imm & MASK)
                elif op == 'slt':
                    value = s32(a) < s32(b)
                else:
                    value = a < b
                self.set(rd, int(value))
            elif op in ('bfoz', 'bfos'):
                msb, lsb = extra
                if msb >= lsb:
                    width = msb - lsb + 1
                    value = (a >> lsb) & ((1 << width) - 1)
                    if op == 'bfos':
                        value = sext(value, width)
                elif msb == 0:
                    # Bit move: rd[lsb] = rs1[0] (reviewer's reading of the
                    # Andes spec; not on any path exercised by the tests).
                    value = (a & 1) << lsb
                    if op == 'bfos':
                        value = sext(value, lsb + 1)
                else:
                    # Insert form: rs1[lsb-msb:0] becomes rd[lsb:msb].
                    width = lsb - msb + 1
                    value = (a & ((1 << width) - 1)) << msb
                    if op == 'bfos':
                        value = sext(value, lsb + 1)
                self.set(rd, value)
            elif op == 'lea':
                self.set(rd, a + (b << imm))
            elif op == 'mul':
                self.set(rd, a * b)
            elif op in ('mulh', 'mulhsu', 'mulhu'):
                left = s32(a) if op != 'mulhu' else a
                right = s32(b) if op == 'mulh' else b
                self.set(rd, (left * right) >> 32)
            elif op in ('div', 'divu', 'rem', 'remu'):
                if op in ('div', 'rem'):
                    left, right = s32(a), s32(b)
                else:
                    left, right = a, b
                if right == 0:
                    value = MASK if op in ('div', 'divu') else left
                elif op == 'div' and left == -2**31 and right == -1:
                    value = left
                elif op == 'rem' and left == -2**31 and right == -1:
                    value = 0
                else:
                    quotient = abs(left) // abs(right)
                    if (left < 0) != (right < 0):
                        quotient = -quotient
                    value = quotient if op in ('div', 'divu') else left - quotient * right
                self.set(rd, value)
            elif op == 'maddr32':
                self.set(rd, x[rd] + a * b)
            elif op == 'msubr32':
                self.set(rd, x[rd] - a * b)
            elif op == 'minw':
                self.set(rd, min(s32(a), s32(b)))
            elif op == 'swap8':
                self.set(rd, ((a & 0x00ff00ff) << 8) | ((a >> 8) & 0x00ff00ff))
            elif op == 'flw':
                self.f[rd] = bus.read((a + imm) & MASK, 4, pc)
            elif op == 'fsw':
                bus.write((a + imm) & MASK, 4, self.f[rs2], pc)
            elif op == 'fence':
                pass
            elif op.startswith('csrr'):
                # For the *i forms the rs1 field is the 5-bit immediate.
                immediate = op.endswith('i')
                operand = rs1 if immediate else a
                kind = op[:-1] if immediate else op
                if kind == 'csrrw':
                    old = self.csr_rw(imm, lambda _: operand)
                elif kind == 'csrrs':
                    old = self.csr_rw(imm, (lambda o: o | operand) if rs1 else None)
                else:
                    old = self.csr_rw(imm, (lambda o: o & ~operand) if rs1 else None)
                self.set(rd, old)
            elif op == 'mret':
                raise Halt('mret')
            else:
                raise Unsupported(f'{op} at {pc:#x}')
            self.pc = nxt
