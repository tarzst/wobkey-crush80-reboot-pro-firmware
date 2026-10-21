"""Pinned RC2 → transparent-layer base used by NativeHeld."""
import hashlib
import struct
import zlib

RC2_SHA256 = "7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88"

ZERO, A0, A1, A3, T0, T5, T6 = 0, 10, 11, 13, 5, 30, 31
LAYER_STRIDE = 256

# (file offset, expected RC2 bytes) of every replaced instruction.
SITES = {
    'main_l1': (0x13420, '6ff09ffe'),   # j 0x13408 after a1 = L1
    'main_l3': (0x13428, '6ff01ffe'),   # j 0x13408 after a1 = L3
    'list_l1': (0x13318, '8b921fb0'),   # nds.addigp t0, -1280
    'list_l3': (0x1366C, '8b961fd0'),   # nds.addigp a3, -768
}
# Dead blocks: (file offset, size, the RC2 branch whose condition is constant).
BLOCKS = {
    'main': (0x135A4, 40, 0x13264),
    'list_l1': (0x1334C, 44, 0x13348),
    'list_l3': (0x1350C, 44, 0x13508),
}


def r_type(funct7, rs2, rs1, funct3, rd, opcode):
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def i_type(imm, rs1, funct3, rd, opcode):
    if not -2048 <= imm < 2048:
        raise ValueError('immediate out of range')
    return (imm & 0xFFF) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def add(rd, rs1, rs2):
    return r_type(0, rs2, rs1, 0, rd, 0x33)


def lbu(rd, rs1):
    return i_type(0, rs1, 4, rd, 0x03)


def addi(rd, rs1, imm):
    return i_type(imm, rs1, 0, rd, 0x13)


def bne(rs1, rs2, offset):
    if offset % 2 or not -4096 <= offset < 4096:
        raise ValueError('branch offset')
    o = offset & 0x1FFF
    return ((o >> 12) & 1) << 31 | ((o >> 5) & 0x3F) << 25 | rs2 << 20 | rs1 << 15 | \
        1 << 12 | ((o >> 1) & 0xF) << 8 | ((o >> 11) & 1) << 7 | 0x63


def jal(rd, offset):
    if offset % 2 or not -(1 << 20) <= offset < (1 << 20):
        raise ValueError('jump offset')
    o = offset & 0x1FFFFF
    return ((o >> 20) & 1) << 31 | ((o >> 1) & 0x3FF) << 21 | ((o >> 11) & 1) << 20 | \
        ((o >> 12) & 0xFF) << 12 | rd << 7 | 0x6F


def helper(start, table, high, low, resume, prefix=b''):
    """Code at file offset `start`: optional replayed instruction, then

        if table[high] == 0 and table[low] == 1: table -= 256
        j resume
    `high`/`low` hold 2*position and 2*position+1; a0 is the only scratch and
    is overwritten by the stock read that follows at `resume`.
    """
    words = [add(A0, table, high), lbu(A0, A0), None,
             add(A0, table, low), lbu(A0, A0), addi(A0, A0, -1), None,
             addi(table, table, -LAYER_STRIDE)]
    code = bytearray(prefix)
    back = start + len(prefix) + 4 * len(words)
    for index, word in enumerate(words):
        pc = start + len(code)
        if word is None:
            word = bne(A0, ZERO, back - pc)
        code += struct.pack('<I', word)
    code += struct.pack('<I', jal(ZERO, resume - (start + len(code))))
    return bytes(code)


def patch(rc2):
    if hashlib.sha256(rc2).hexdigest() != RC2_SHA256:
        raise ValueError('input must be the pinned RC2 image')
    image = bytearray(rc2)
    for name, (offset, before) in SITES.items():
        if image[offset:offset + 4].hex() != before:
            raise ValueError(f'unexpected RC2 bytes at {name} {offset:#x}')
    main_start, main_size, _ = BLOCKS['main']
    l1_start, l1_size, _ = BLOCKS['list_l1']
    l3_start, l3_size, _ = BLOCKS['list_l3']
    helpers = {
        'main': helper(main_start, A1, A3, T5, 0x13408),
        'list_l1': helper(l1_start, T0, A1, T6, 0x1331C, prefix=bytes.fromhex(SITES['list_l1'][1])),
        'list_l3': helper(l3_start, A3, A1, T6, 0x13670, prefix=bytes.fromhex(SITES['list_l3'][1])),
    }
    for name, code in helpers.items():
        start, size, _ = BLOCKS[name]
        if len(code) > size:
            raise ValueError(f'{name} helper needs {len(code)} bytes, block has {size}')
        image[start:start + len(code)] = code
    jumps = {'main_l1': main_start, 'main_l3': main_start,
             'list_l1': l1_start, 'list_l3': l3_start}
    for name, target in jumps.items():
        offset = SITES[name][0]
        image[offset:offset + 4] = struct.pack('<I', jal(ZERO, target - offset))
    image[-4:] = struct.pack('<I', (~zlib.crc32(image[:-4])) & 0xFFFFFFFF)
    if zlib.crc32(image) != 0xFFFFFFFF or len(image) != len(rc2):
        raise ValueError('CRC/length check failed')
    return bytes(image), helpers


def diff_ranges(a, b):
    ranges, i = [], 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]:
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    return ranges
