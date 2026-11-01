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

from nativeheld.elf_layout import audit_gp, sections, symbols
from nativeheld.trns import jal, patch as patch_trns

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/nativeheld'
RELEASE_MANIFEST = ROOT / 'firmware/nativeheld/manifest.json'
OUTPUT_SHA256 = '7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35'
TRNS_SHA256 = '31722203eab882eb436b80c2bf02ee54d32c125b7474700c40a220c2b883918b'
XIP = 0x20000000
CFLAGS = ['-std=c11', '-Wall', '-Wextra', '-Wconversion', '-Wshadow', '-Werror', '-Wpedantic',
          '-march=rv32imac_zicsr', '-mabi=ilp32', '-ffreestanding', '-fno-builtin',
          '-fno-pic', '-msmall-data-limit=0', '-ffunction-sections', '-fdata-sections',
          '-fstack-usage', '-fno-tree-loop-distribute-patterns', '-fno-jump-tables']
MODULES = ['compact_holds.c', 'delta_adapter.c', 'macro_stream.c', 'firmware_binding.c', 'via_commands.c']
FIXED_SECTIONS = {'.text.cdb_hook_reset_common': 0xcccc, '.text.cdb_macro_poll': 0x13df8}
HOOK_SPECS = [
    ('cdb_hook_physical', 0x13268, 0, 'JAL'),
    ('cdb_hook_synthetic', 0x8fbc, 0, 'JAL'),
    ('cdb_hook_reset_common', 0xcccc, 0, 'replaced-component-entry'),
    ('cdb_macro_poll', 0x13df8, 0, 'replaced-component-entry'),
    ('cdb_hook_ready', 0x1ade0, 0, 'JAL'),
    ('cdb_hook_via', 0xda04, 0, 'JAL'),
    ('cdb_macro_scan', 0xec20, 1, 'JAL'),
    ('cdb_macro_empty', 0xedbc, 1, 'JAL'),
    ('cdb_reset_begin', 0x10c14, 1, 'JAL'),
    ('cdb_reset_end', 0x10c50, 1, 'JAL'),
    ('cdb_reset_begin', 0x110b8, 1, 'JAL'),
    ('cdb_reset_end', 0x110ec, 1, 'JAL'),
    ('cdb_reset_begin', 0x12934, 1, 'JAL'),
    ('cdb_reset_end', 0x12968, 1, 'JAL'),
    ('cdb_reset_begin', 0x1b728, 1, 'JAL'),
    ('cdb_reset_end', 0x1b758, 1, 'JAL'),
    ('cdb_reset_begin', 0x1aacc, 1, 'JAL'),
    ('cdb_reset_end', 0x1ab30, 1, 'JAL'),
]


def align_up(value, alignment):
    return (value + alignment - 1) & ~(alignment - 1)


def find_compiler(cc):
    found = shutil.which(cc)
    if found:
        return found
    fallback = ROOT.parent / 'crush80-fix/via-research-20261010/toolchain/root/usr/bin' / cc
    if fallback.is_file():
        return str(fallback)
    raise ValueError(f'RISC-V compiler not found: {cc}; see docs/NATIVEHELD.md')


def load_plan(path=None):
    plan = json.loads((SOURCE / 'plan.json' if path is None else Path(path)).read_text())
    if (plan['base_sha256'], plan['size']) != (TRNS_SHA256, 124436):
        raise ValueError('placement plan does not match transparent-layer base')
    return plan


def load_release_plan():
    manifest = json.loads(RELEASE_MANIFEST.read_text())
    return {
        'regions': manifest['regions'],
        'allocated_bytes': manifest['allocated_bytes'],
        'capacity_bytes': manifest['capacity_bytes'],
        'linked_sections': manifest['linked_sections'],
        'base_sha256': manifest['base_sha256'],
        'output_sha256': manifest['image']['sha256'],
        'output_crc': manifest['image']['ota_crc'],
        'size': manifest['image']['size'],
        'hooks': manifest['hooks'],
        'protected_ranges': manifest['protected_ranges'],
    }


def compile_payload(cc, build_dir, plan, script_path=None):
    compiler = find_compiler(cc)
    build_dir.mkdir(parents=True, exist_ok=True)
    memory, elf = build_dir / 'memory.o', build_dir / 'payload.elf'
    script = SOURCE / 'layout.ld' if script_path is None else script_path
    subprocess.run([compiler, *CFLAGS, '-Os', '-march=rv32imac', '-c',
                    str(SOURCE / 'core/freestanding_memory.c'), '-o', str(memory)], check=True)
    args = [compiler, *CFLAGS, '-Oz', '-flto', '-save-temps=obj', '-nostdlib', '-nostartfiles',
            '-Wl,--gc-sections', '-Wl,--relax', '-Wl,--no-relax-gp', '-Wl,--orphan-handling=error',
            f'-Wl,-T,{script}', f'-Wl,-Map={build_dir / "payload.map"}']
    args += [f'-Wl,--undefined={name}' for name in plan['roots']]
    args += [f'-Wl,--defsym={name}={value:#x}' for name, value in plan['absolute_symbols'].items()]
    args += [str(SOURCE / 'compact' / name) for name in MODULES]
    args += [str(SOURCE / 'compact/firmware_hooks.S'), str(SOURCE / 'core/irq_guard.S'),
             str(memory), '-o', str(elf)]
    subprocess.run(args, check=True)
    return elf.read_bytes()


def subset_pack(items, bounds):
    fixed_placed = {i: [] for i in range(len(bounds))}
    cursors = [a for a, _ in bounds]
    remaining = []
    for item in items:
        if item['section'] in FIXED_SECTIONS:
            target = FIXED_SECTIONS[item['section']]
            idx = next(i for i, (a, b) in enumerate(bounds) if a <= target and target + item['size'] <= b)
            if align_up(cursors[idx], item['align']) != target:
                raise ValueError(f'fixed section cannot start at {target:#x}')
            fixed_placed[idx].append(item)
            cursors[idx] = target + item['size']
        else:
            remaining.append(item)
    import random
    for seed in range(256):
        rng = random.Random(seed)
        shuffled = list(remaining)
        rng.shuffle(shuffled)
        ordered = sorted(shuffled, key=lambda x: (-x['size'], -x['align']))
        placed = {i: list(fixed_placed[i]) for i in range(len(bounds))}
        cur = list(cursors)
        ok = True
        for item in ordered:
            candidates = [
                i for i, (_, b) in enumerate(bounds)
                if align_up(cur[i], item['align']) + item['size'] <= b
            ]
            if not candidates:
                ok = False
                break
            best = min(
                candidates,
                key=lambda i: (
                    bounds[i][1] - (align_up(cur[i], item['align']) + item['size']),
                    rng.random(),
                ),
            )
            cur[best] = align_up(cur[best], item['align']) + item['size']
            placed[best].append(item)
        if ok:
            return [placed[i] for i in range(len(bounds))]
    orders = [
        sorted(range(len(bounds)), key=lambda i: bounds[i][1] - cursors[i]),
        sorted(range(len(bounds)), key=lambda i: -(bounds[i][1] - cursors[i])),
    ]
    for tie in (-1, 1):
        for order in orders:
            rem = list(remaining)
            placed = {}
            for idx in order:
                start, end = cursors[idx], bounds[idx][1]
                states = {start: []}
                for item in sorted(rem, key=lambda x: (-x['align'], -x['size'], x['section'])):
                    nxt = dict(states)
                    for pos, chosen in states.items():
                        pos2 = align_up(pos, item['align']) + item['size']
                        if pos2 <= end and (pos2 not in nxt or (tie * len(chosen) < tie * len(nxt[pos2]))):
                            nxt[pos2] = [*chosen, item]
                    states = nxt
                best_pos = max(states, key=lambda p: (p, tie * len(states[p])))
                chosen = states[best_pos]
                placed[idx] = [*fixed_placed[idx], *chosen]
                used = {x['section'] for x in chosen}
                rem = [x for x in rem if x['section'] not in used]
            if not rem:
                return [placed[i] for i in range(len(bounds))]
    raise ValueError(f'unplaced sections: {[x["section"] for x in rem]}')


def render_script(groups, bounds, asserts=True):
    lines = ['OUTPUT_ARCH(riscv)', 'ENTRY(cdb_hook_physical)', 'SECTIONS {']
    for index, (items, (start, end)) in enumerate(zip(groups, bounds)):
        if not items:
            continue
        lines.append(f'  . = {XIP + start:#x};')
        for item in items:
            lines.append(f'  {item["section"]} ALIGN({item["align"]}) : {{ *({item["pattern"]}) }}')
        if asserts:
            lines.append(f'  ASSERT(. <= {XIP + end:#x}, "replacement region {index} overflow")')
    lines += [
        '  .forbidden 0 : { *(.data .data.* .sdata .sdata.* .bss .bss.* .sbss .sbss.* COMMON)',
        '    *(.got .got.* .iplt .rela.*) }',
        '  ASSERT(SIZEOF(.forbidden) == 0, "implicit RAM or unsupported dynamic allocation")',
        '  /DISCARD/ : { *(.comment .riscv.attributes .note.GNU-stack) }',
        '}',
    ]
    return '\n'.join(lines) + '\n'


def repack_payload(cc, build_dir, rc2):
    compiler = find_compiler(cc)
    plan = json.loads((SOURCE / 'plan.json').read_text())
    bounds = [tuple(r) for r in plan['regions']]
    build_dir.mkdir(parents=True, exist_ok=True)
    memory, unplaced = build_dir / 'memory.o', build_dir / 'unplaced.elf'
    subprocess.run([compiler, *CFLAGS, '-Os', '-march=rv32imac', '-c',
                    str(SOURCE / 'core/freestanding_memory.c'), '-o', str(memory)], check=True)
    args = [compiler, *CFLAGS, '-Oz', '-flto', '-nostdlib', '-nostartfiles',
            '-Wl,--gc-sections', '-Wl,--relax', '-Wl,--no-relax-gp',
            '-Wl,--unique=.text.*', '-Wl,--unique=.rodata.*',
            '-Wl,--entry=cdb_hook_physical', '-Wl,-Ttext=0x20030000']
    args += [f'-Wl,--undefined={name}' for name in plan['roots']]
    args += [f'-Wl,--defsym={name}={value:#x}' for name, value in plan['absolute_symbols'].items()]
    args += [str(SOURCE / 'compact' / name) for name in MODULES]
    args += [str(SOURCE / 'compact/firmware_hooks.S'), str(SOURCE / 'core/irq_guard.S'),
             str(memory), '-o', str(unplaced)]
    subprocess.run(args, check=True)
    items = []
    for s in sections(unplaced.read_bytes()):
        if not (s.flags & 2 and s.size):
            continue
        out_name = '.text.irq_guard' if s.name == '.text' else s.name
        items.append({'section': out_name, 'pattern': s.name,
                      'size': s.size, 'align': max(s.alignment, 2)})
    flat_file = build_dir / 'flat.ld'
    flat_file.write_text(render_script([items], [(0x10000, 0x18000)], asserts=False))
    flat_elf = compile_payload(compiler, build_dir, plan, flat_file)
    flat_sizes = {s.name: s.size for s in sections(flat_elf) if s.flags & 2 and s.size}
    for it in items:
        it['size'] = flat_sizes.get(it['section'], it['size'])
    for _ in range(3):
        groups = subset_pack(items, bounds)
        probe_file = build_dir / 'probe.ld'
        probe_file.write_text(render_script(groups, bounds, asserts=False))
        probe_elf = compile_payload(compiler, build_dir, plan, probe_file)
        actual = {s.name: s.size for s in sections(probe_elf) if s.flags & 2 and s.size}
        if all(actual.get(it['section'], it['size']) <= it['size'] for it in items):
            break
        for it in items:
            it['size'] = max(it['size'], actual.get(it['section'], it['size']))
    script_text = render_script(groups, bounds, asserts=True)
    script_file = build_dir / 'repack.ld'
    script_file.write_text(script_text)
    elf = compile_payload(compiler, build_dir, plan, script_file)
    audit_gp(elf)
    syms = symbols(elf)
    alloc = [s for s in sections(elf) if s.flags & 2 and s.size]
    plan['allocated_bytes'] = sum(s.size for s in alloc)
    plan['linked_sections'] = [
        {'name': s.name, 'address': s.address, 'size': s.size,
         'sha256': hashlib.sha256(s.data).hexdigest()}
        for s in alloc
    ]
    plan['hooks'] = [
        {'offset': offset, 'target': syms[symbol], 'link_register': rd, 'symbol': symbol, 'kind': kind}
        for symbol, offset, rd, kind in HOOK_SPECS
    ]
    plan['output_sha256'] = None
    image = assemble(rc2, elf, plan)
    plan['output_sha256'] = hashlib.sha256(image).hexdigest()
    plan['output_crc'] = f'{struct.unpack_from("<I", image, len(image) - 4)[0]:08x}'
    (SOURCE / 'layout.ld').write_text(script_text)
    (SOURCE / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    if RELEASE_MANIFEST.exists():
        manifest = json.loads(RELEASE_MANIFEST.read_text())
        if 'release_sources' not in manifest and 'sources' in manifest:
            manifest['release_sources'] = manifest['sources']
        tracked = sorted([
            *SOURCE.glob('compact/*.[chS]'),
            *SOURCE.glob('core/*.[chS]'),
            SOURCE / 'elf_layout.py',
            SOURCE / 'layout.ld',
            SOURCE / 'plan.json',
            SOURCE / 'toolchain.json',
            SOURCE / 'trns.py',
            ROOT / 'src/build_nativeheld.py',
        ])
        manifest['sources'] = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tracked
        }
        RELEASE_MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    checksums = ROOT / 'SHA256SUMS'
    if checksums.exists():
        fixed = [
            'firmware/official/Crush80-RGB-20260618-official.bin',
            'firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin',
            'firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin',
            'firmware/nativeheld/NativeHeld-20261021.elf',
            'firmware/nativeheld/manifest.json',
            'via/Crush80-RGB-USB.json',
            'src/build_firmware.py',
            'src/build_nativeheld.py',
            'tools/crush80.py',
            *(str(p.relative_to(ROOT)) for p in sorted([
                *SOURCE.glob('compact/*.[chS]'),
                *SOURCE.glob('core/*.[chS]'),
                SOURCE / 'elf_layout.py',
                SOURCE / 'layout.ld',
                SOURCE / 'plan.json',
                SOURCE / 'toolchain.json',
                SOURCE / 'trns.py',
            ])),
        ]
        checksums.write_text(''.join(
            f'{hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()}  {rel}\n'
            for rel in fixed
        ))
    return elf, image, plan


def assemble(rc2, elf, plan=None):
    if plan is None:
        current = load_plan()
        names = {s.name for s in sections(elf) if s.flags & 2 and s.size}
        if names == {s['name'] for s in current['linked_sections']}:
            plan = current
        else:
            plan = load_release_plan()
    base, _ = patch_trns(rc2)
    if hashlib.sha256(base).hexdigest() != TRNS_SHA256:
        raise ValueError('transparent-layer base SHA-256 mismatch')
    audit_gp(elf)
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
    expected_sha = plan.get('output_sha256')
    if len(image) != 124436 or zlib.crc32(image) != 0xffffffff or \
            (expected_sha is not None and hashlib.sha256(image).hexdigest() != expected_sha):
        raise ValueError('reproduced firmware length, CRC or SHA-256 differs from tested image')
    return bytes(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/Crush80-RGB-0108-NativeHeld-20261021.bin')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build/nativeheld')
    parser.add_argument('--cc', default='riscv64-unknown-elf-gcc')
    parser.add_argument('--repack', action='store_true', help='recompute section packing, layout.ld and plan.json')
    parser.add_argument('--verify', action='store_true', help='verify published release image from reference ELF')
    args = parser.parse_args()
    rc2 = args.source.read_bytes()
    if args.verify:
        ref_elf = (ROOT / 'firmware/nativeheld/NativeHeld-20261021.elf').read_bytes()
        published = (ROOT / 'firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin').read_bytes()
        image = assemble(rc2, ref_elf)
        if image != published:
            raise ValueError('reconstructed image does not match published NativeHeld release')
        print(f'verified published release: {len(image)} bytes, SHA-256 {OUTPUT_SHA256}, OTA CRC 350ad5c5')
        return
    if args.repack:
        _, image, plan = repack_payload(args.cc, args.build_dir.resolve(), rc2)
    else:
        plan = load_plan()
        image = assemble(rc2, compile_payload(args.cc, args.build_dir.resolve(), plan), plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f'{args.output}: {len(image)} bytes, allocated {plan["allocated_bytes"]}/{plan["capacity_bytes"]} B, '
          f'SHA-256 {plan["output_sha256"]}, OTA CRC {plan["output_crc"]}')



if __name__ == '__main__':
    main()
