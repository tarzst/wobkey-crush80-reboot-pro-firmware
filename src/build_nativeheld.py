#!/usr/bin/env python3
"""Reproduce the exact hardware-tested NativeHeld 2026-10-21 application image.

Compiles the published C/assembly into its fixed verified placement, applies
the TRNS and entry patches to pinned RC2, then requires the tested SHA-256.
This program has no HID/device access and does not change the flasher policy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

from nativeheld.elf_layout import sections
from nativeheld.trns import jal, patch as patch_trns

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/nativeheld'
OUTPUT_SHA256 = '7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35'
TRNS_SHA256 = '31722203eab882eb436b80c2bf02ee54d32c125b7474700c40a220c2b883918b'
XIP = 0x20000000
CFLAGS = ['-std=c11', '-Wall', '-Wextra', '-Wconversion', '-Wshadow', '-Werror', '-Wpedantic',
          '-march=rv32imac_zicsr', '-mabi=ilp32', '-Os', '-ffreestanding', '-fno-builtin',
          '-fno-pic', '-msmall-data-limit=0', '-ffunction-sections', '-fdata-sections',
          '-fstack-usage', '-fno-tree-loop-distribute-patterns']
MODULES = ['compact_holds.c', 'delta_adapter.c', 'macro_stream.c', 'firmware_binding.c', 'via_commands.c']


def load_plan():
    plan = json.loads((SOURCE / 'plan.json').read_text())
    if (plan['base_sha256'], plan['output_sha256'], plan['size']) != (TRNS_SHA256, OUTPUT_SHA256, 124436):
        raise ValueError('placement plan does not describe the pinned NativeHeld release')
    return plan


def compile_payload(cc, build_dir, plan):
    compiler = shutil.which(cc)
    if compiler is None:
        raise ValueError(f'RISC-V compiler not found: {cc}; see docs/NATIVEHELD.md')
    build_dir.mkdir(parents=True, exist_ok=True)
    memory, elf = build_dir / 'memory.o', build_dir / 'payload.elf'
    subprocess.run([compiler, *CFLAGS, '-march=rv32imac', '-c',
                    str(SOURCE / 'core/freestanding_memory.c'), '-o', str(memory)], check=True)
    args = [compiler, *CFLAGS, '-Oz', '-flto', '-save-temps=obj', '-nostdlib', '-nostartfiles',
            '-Wl,--gc-sections', '-Wl,--relax', '-Wl,--no-relax-gp', '-Wl,--orphan-handling=error',
            f'-Wl,-T,{SOURCE / "layout.ld"}', f'-Wl,-Map={build_dir / "payload.map"}']
    args += [f'-Wl,--undefined={name}' for name in plan['roots']]
    args += [f'-Wl,--defsym={name}={value:#x}' for name, value in plan['absolute_symbols'].items()]
    args += [str(SOURCE / 'compact' / name) for name in MODULES]
    args += [str(SOURCE / 'compact/firmware_hooks.S'), str(SOURCE / 'core/irq_guard.S'),
             str(memory), '-o', str(elf)]
    subprocess.run(args, check=True)
    return elf.read_bytes()


def assemble(rc2, elf, plan=None):
    plan = load_plan() if plan is None else plan
    base, _ = patch_trns(rc2)
    if hashlib.sha256(base).hexdigest() != TRNS_SHA256:
        raise ValueError('transparent-layer base SHA-256 mismatch')
    payload = [s for s in sections(elf) if s.flags & 2 and s.size]
    expected = {s['name']: s for s in plan['linked_sections']}
    if len(payload) != len(expected) or {s.name for s in payload} != set(expected):
        raise ValueError('unexpected allocated sections; possible RAM allocation or compiler mismatch')
    image, occupied = bytearray(base), []
    for section in payload:
        record = expected[section.name]
        a, b = section.address - XIP, section.address - XIP + section.size
        if section.kind != 1 or section.flags & 1 or section.address % max(section.alignment, 2) or \
                not 0 <= a < b <= len(image) - 4 or \
                not any(start <= a and b <= end for start, end in plan['regions']) or \
                any(a < end and start < b for start, end in occupied):
            raise ValueError(f'invalid read-only placement: {section.name}')
        if (section.address, section.size, hashlib.sha256(section.data).hexdigest()) != \
                (record['address'], record['size'], record['sha256']):
            raise ValueError(f'compiled section differs from tested bytes: {section.name}; check toolchain version')
        image[a:b] = section.data
        occupied.append((a, b))
    for hook in plan['hooks']:
        offset, target, rd = hook['offset'], hook['target'], hook['link_register']
        if rd not in (0, 1) or not any(s.flags & 4 and s.address == target for s in payload):
            raise ValueError('hook target is not a tested executable section entry')
        if target == XIP + offset:
            if rd:
                raise ValueError('fixed component entry cannot replace a linked call')
            continue
        if not 0 <= offset <= len(image) - 8 or any(offset < b and a < offset + 4 for a, b in occupied):
            raise ValueError('hook overlaps payload or image trailer')
        image[offset:offset + 4] = struct.pack('<I', jal(rd, target - XIP - offset))
    image[-4:] = struct.pack('<I', ~zlib.crc32(image[:-4]) & 0xffffffff)
    for a, b in plan['protected_ranges']:
        if image[a:b] != base[a:b]:
            raise ValueError('startup or initializer source changed')
    if len(image) != 124436 or zlib.crc32(image) != 0xffffffff or \
            hashlib.sha256(image).hexdigest() != OUTPUT_SHA256:
        raise ValueError('reproduced firmware length, CRC or SHA-256 differs from tested image')
    return bytes(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/Crush80-RGB-0108-NativeHeld-20261021.bin')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build/nativeheld')
    parser.add_argument('--cc', default='riscv64-unknown-elf-gcc')
    args = parser.parse_args()
    plan = load_plan()
    image = assemble(args.source.read_bytes(), compile_payload(args.cc, args.build_dir.resolve(), plan), plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f'{args.output}: {len(image)} bytes, SHA-256 {OUTPUT_SHA256}, OTA CRC {plan["output_crc"]}')


if __name__ == '__main__':
    main()
