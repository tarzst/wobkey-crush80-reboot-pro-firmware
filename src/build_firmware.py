#!/usr/bin/env python3
"""Reproduce the Crush 80 RGB 20260618 Mac-layer RC2 patch."""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib

SOURCE_SIZE = 124436
SOURCE_SHA256 = 'b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da'
OUTPUT_SHA256 = '7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88'
CODE_CAVE = 0x10A8
LAYER_LOAD = 0x13230

MAC_PATCHES = (
    (0x12C5C, '03c6a801', '13060000'),
    (0x13258, '834fab01', '930f0000'),
    (0x13338, '8342ab01', '93020000'),
    (0x134F8, '8342ab01', '93020000'),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack32(value):
    return struct.pack('<I', value & 0xffffffff)


def branch(rs1, rs2, funct3, offset):
    if offset % 2 or not -4096 <= offset <= 4094:
        raise ValueError('invalid branch offset')
    imm = offset & 0x1fff
    return pack32(((imm >> 12) << 31) | (((imm >> 5) & 0x3f) << 25) |
                  (rs2 << 20) | (rs1 << 15) | (funct3 << 12) |
                  (((imm >> 1) & 0xf) << 8) | (((imm >> 11) & 1) << 7) | 0x63)


def jump(offset):
    if offset % 2 or not -(1 << 20) <= offset < (1 << 20):
        raise ValueError('invalid jump offset')
    imm = offset & 0x1fffff
    return pack32(((imm >> 20) << 31) | (((imm >> 1) & 0x3ff) << 21) |
                  (((imm >> 11) & 1) << 20) | (((imm >> 12) & 0xff) << 12) | 0x6f)


def layer_code():
    code = bytearray.fromhex('8b658017')       # a1 = active dynamic layer
    code += bytes.fromhex('8342ab01')          # t0 = Win/Mac flag
    code += branch(5, 0, 0, 16)                # Windows: keep layer
    code += bytes.fromhex('930f2000')          # t6 = 2
    code += branch(11, 31, 7, 8)               # layer >= 2: keep layer
    code += bytes.fromhex('93852500')           # macOS: layer += 2
    code += jump((LAYER_LOAD + 4) - (CODE_CAVE + 24))
    return bytes(code)


def validate(image, exact_source=False):
    if len(image) != SOURCE_SIZE or image[32:36] != b'KNLT':
        raise ValueError('wrong image size or header')
    if int.from_bytes(image[24:28], 'little') != len(image):
        raise ValueError('internal size mismatch')
    if zlib.crc32(image) != 0xffffffff:
        raise ValueError('firmware CRC mismatch')
    if exact_source and sha256(image) != SOURCE_SHA256:
        raise ValueError('input is not the exact official 20260618 image')


def patch(source):
    validate(source, exact_source=True)
    image = bytearray(source)
    for offset, before, after in MAC_PATCHES:
        if image[offset:offset+4] != bytes.fromhex(before):
            raise ValueError(f'unexpected patch site at {offset:#x}')
        image[offset:offset+4] = bytes.fromhex(after)
    code = layer_code()
    if any(image[CODE_CAVE:CODE_CAVE+len(code)]):
        raise ValueError('code cave is not empty')
    if image[LAYER_LOAD:LAYER_LOAD+4] != bytes.fromhex('8b658017'):
        raise ValueError('unexpected layer-load instruction')
    image[CODE_CAVE:CODE_CAVE+len(code)] = code
    image[LAYER_LOAD:LAYER_LOAD+4] = jump(CODE_CAVE-LAYER_LOAD)
    image[-4:] = pack32((~zlib.crc32(image[:-4])) & 0xffffffff)
    result = bytes(image)
    validate(result)
    if sha256(result) != OUTPUT_SHA256:
        raise ValueError('reproduced image SHA-256 mismatch')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = patch(args.source.read_bytes())
    args.output.write_bytes(result)
    print(f'{args.output}: {len(result)} bytes, SHA-256 {sha256(result)}')


if __name__ == '__main__':
    main()
