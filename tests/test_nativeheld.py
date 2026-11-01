import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_nativeheld import OUTPUT_SHA256, assemble, compile_payload, load_plan
from nativeheld.elf_layout import audit_gp, sections, symbols
from nativeheld.trns import patch as trns_patch
from rc2emu.coldstart import Live
from rc2emu.keyboard import Keyboard
from test_firmware import load_tool

LOCAL_RISCV_CC = ROOT.parent / 'crush80-fix/via-research-20261010/toolchain/root/usr/bin/riscv64-unknown-elf-gcc'
RISCV_CC = shutil.which('riscv64-unknown-elf-gcc') or (str(LOCAL_RISCV_CC) if LOCAL_RISCV_CC.exists() else None)


class NativeHeldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rc2 = (ROOT / 'firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin').read_bytes()
        cls.image = (ROOT / 'firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin').read_bytes()
        cls.elf = (ROOT / 'firmware/nativeheld/NativeHeld-20261021.elf').read_bytes()
        cls.plan = load_plan()

    def test_exact_image_reconstructs_from_published_payload_and_rc2(self):
        self.assertEqual(hashlib.sha256(self.image).hexdigest(), OUTPUT_SHA256)
        self.assertEqual(assemble(self.rc2, self.elf), self.image)
        self.assertEqual(len(self.image), 124436)
        self.assertEqual(struct.unpack_from('<I', self.image, 24)[0], len(self.image))
        self.assertEqual(zlib.crc32(self.image), 0xffffffff)
        base, _ = trns_patch(self.rc2)
        for a, b in self.plan['protected_ranges']:
            self.assertEqual(self.image[a:b], base[a:b])
        self.assertEqual(len(self.plan['hooks']), 18)
        self.assertEqual(len({h['offset'] for h in self.plan['hooks']}), 18)

    def test_only_declared_sections_hooks_and_crc_differ(self):
        base, _ = trns_patch(self.rc2)
        allowed = [(s.address - 0x20000000, s.address - 0x20000000 + s.size)
                   for s in sections(self.elf) if s.flags & 2 and s.size]
        allowed += [(h['offset'], h['offset'] + 4) for h in self.plan['hooks']]
        allowed.append((len(base) - 4, len(base)))
        for i, (a, b) in enumerate(zip(base, self.image)):
            if a != b:
                self.assertTrue(any(start <= i < end for start, end in allowed), hex(i))

    def test_corrupt_source_and_payload_are_rejected(self):
        damaged = bytearray(self.rc2)
        damaged[0x1000] ^= 1
        with self.assertRaises(ValueError):
            assemble(bytes(damaged), self.elf)
        shoff = struct.unpack_from('<I', self.elf, 32)[0]
        payload_index = next(i for i, s in enumerate(sections(self.elf)) if s.flags & 4 and s.size)
        offset = struct.unpack_from('<I', self.elf, shoff + payload_index * 40 + 16)[0]
        damaged = bytearray(self.elf)
        damaged[offset] ^= 1
        with self.assertRaisesRegex(ValueError, 'differs from tested bytes'):
            assemble(self.rc2, bytes(damaged))
        damaged = bytearray(self.elf)
        flags_at = shoff + payload_index * 40 + 8
        flags = struct.unpack_from('<I', damaged, flags_at)[0]
        struct.pack_into('<I', damaged, flags_at, flags | 1)
        with self.assertRaisesRegex(ValueError, 'invalid read-only placement'):
            assemble(self.rc2, bytes(damaged))

    def test_manifest_and_checksums_match_public_files(self):
        manifest = json.loads((ROOT / 'firmware/nativeheld/manifest.json').read_text())
        for name, digest in manifest['sources'].items():
            self.assertFalse(Path(name).is_absolute())
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(hashlib.sha256(self.elf).hexdigest(), manifest['payload']['sha256'])
        for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split(None, 1)
            self.assertEqual(hashlib.sha256((ROOT / name.strip()).read_bytes()).hexdigest(), digest, name)

    def test_exact_flasher_policy_and_rollback(self):
        tool = load_tool()
        self.assertEqual(tool.reject_unsafe_image(self.image), OUTPUT_SHA256)
        for crc in (0xca2d85dc, 0xfe1aa4c2, 0x54ab7ac3, 0xdca8651c, 0x350ad5c5):
            tool.validate_flash_transition(OUTPUT_SHA256, crc)
        with self.assertRaises(RuntimeError):
            tool.validate_flash_transition(OUTPUT_SHA256, 0x12345678)
        for old in ('b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da',
                    '7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88'):
            tool.validate_flash_transition(old, 0x350ad5c5)
        altered = bytearray(self.image)
        altered[0x1000] ^= 1
        altered[-4:] = struct.pack('<I', ~zlib.crc32(altered[:-4]) & 0xffffffff)
        with self.assertRaises(ValueError):
            tool.reject_unsafe_image(altered)

    @unittest.skipUnless(shutil.which('cc'), 'native C checks require a host C compiler')
    def test_native_ownership_and_streaming_macros(self):
        source = ROOT / 'src/nativeheld'
        with tempfile.TemporaryDirectory(prefix='crush80-native-test-') as folder:
            executable = Path(folder) / 'check'
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wpedantic',
                            '-I', str(source / 'compact'), str(ROOT / 'tests/nativeheld_check.c'),
                            *[str(source / 'compact' / name) for name in
                              ('compact_holds.c', 'delta_adapter.c', 'macro_stream.c')],
                            '-o', str(executable)], check=True, timeout=30)
            subprocess.run([str(executable)], check=True, timeout=10)

    def test_elf_symbols_and_gp_audit(self):
        syms = symbols(self.elf)
        self.assertIn('cdb_hook_physical', syms)
        self.assertIn('cdb_via_packet', syms)
        self.assertEqual(audit_gp(self.elf), [syms['cdb_oem_common']])

    def test_rc2emu_cold_start_and_live_chords(self):
        keymap = [[0] * 128 for _ in range(4)]
        keymap[0][0] = 0x0104  # LCTL(KC_A)
        keymap[0][1] = 0x0005  # KC_B
        keymap[0][2] = 0x5221  # MO(1)
        keymap[1][1] = 0x0001  # KC_TRNS -> falls back to KC_B on layer 0
        keymap[1][2] = 0x0001
        live = Live(self.image, keymap=keymap)
        live.run(300)
        self.assertEqual(live.m.gp(929), 8)
        self.assertEqual(live.m.cpu.csr[0x300] & 8, 8)
        live.take()
        live.event(0, True)
        self.assertEqual(live.take(1)[-1], '0100040000000000')
        live.event(1, True)
        self.assertEqual(live.take(1)[-1], '0100040500000000')
        live.event(0, False)
        self.assertEqual(live.take(1)[-1], '0000000500000000')
        live.event(2, True)
        live.event(1, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        live.event(1, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(1, False)
        live.event(2, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        self.assertEqual(live.m.cpu.csr[0x300] & 8, 8)

    def test_rc2emu_macro_interrupt_and_reset_scopes(self):
        keymap = [[0] * 128 for _ in range(4)]
        keymap[0][1] = 0x0104  # LCTL(KC_A)
        macros = bytearray(b'a\x00'.ljust(512, b'\x00'))
        kb = Keyboard(keymap, macros=macros, image=self.image, fast_delay=True)
        m = kb.machine
        m.bus.poke(0x9F000, bytes([0xA5]) * 4096)
        m.cpu.csr[0x300] = 8
        m.cpu.hooks[0x2001ADE4] = m._returned
        m.set_gp(929, 7)
        m.cpu.x[10] = 0x80800 + 929
        m.cpu.x[13] = 8
        m.call(0x2001ADE0)
        m.cpu.hooks.pop(0x2001ADE4, None)
        self.assertEqual(m.gp(929), 8)
        kb.key(1, True)
        self.assertEqual(m.bus.peek(0x80800 + 848, 8).hex(), '0100040000000000')
        # Verify atomic reset scope (0x1B728..0x1B75C) clears both stock buffers and NativeHeld state
        m.cpu.hooks[0x2001B75C] = m._returned
        m.cpu.hooks[0x2001B63C] = m._returned
        m.cpu.x[8] = 0x80800 + 804
        m.cpu.x[9] = 0x02
        m.call(0x2001B728)
        m.cpu.hooks.pop(0x2001B75C, None)
        m.cpu.hooks.pop(0x2001B63C, None)
        self.assertEqual(m.bus.peek(0x80800 + 848, 8).hex(), '0000000000000000')
        self.assertEqual(m.cpu.csr[0x300] & 8, 8)
        # Verify streaming macro execution and re-entrancy guard during flash read
        seen_guard = []
        orig_flash_read = kb._flash_read

        def hooked_flash_read(mm):
            seen_guard.append(mm.bus.peek(0x80BE4 + 445, 1)[0])
            return orig_flash_read(mm)

        m.stub(0x2000D510, hooked_flash_read)
        kb.take()
        m.set_gp(392, 0)
        m.set_gp(813, m.gp(813) | 4)
        kb.idle(20)
        self.assertEqual(seen_guard, [1])
        ep1 = [data for ep, data, _ in kb.take() if ep == 1]
        self.assertIn('0000040000000000', ep1)
        self.assertEqual(ep1[-1], '0000000000000000')

    @unittest.skipUnless(RISCV_CC, 'RISC-V build test requires riscv64-unknown-elf-gcc')
    def test_refactored_source_builds_and_eliminates_redundant_flash_writes(self):
        with tempfile.TemporaryDirectory(prefix='crush80-riscv-test-') as folder:
            elf = compile_payload(RISCV_CC, Path(folder), self.plan)
        syms = symbols(elf)
        self.assertEqual(audit_gp(elf), [syms['cdb_oem_common']])
        built = assemble(self.rc2, elf, plan=self.plan)
        keymap = [[0] * 128 for _ in range(4)]
        keymap[0][0] = 0x0104  # LCTL(KC_A)
        keymap[0][1] = 0x2204  # MT(MOD_LSFT, KC_A)
        keymap[0][2] = 0x0005  # KC_B
        keymap[0][3] = 0x412C  # LT(1, KC_SPC)
        keymap[0][4] = 0x5281  # OSL(1)
        keymap[0][5] = 0x5261  # TG(1)
        keymap[0][6] = 0x52C1  # TT(1)
        keymap[0][7] = 0x5F10  # FN_MO13
        keymap[0][8] = 0x5222  # MO(2)
        keymap[0][9] = 0x5242  # DF(2)
        keymap[0][10] = 0x00E1  # KC_LSFT
        keymap[0][11] = 0x00E5  # KC_RSFT
        keymap[0][12] = 0x002D  # KC_MINS
        keymap[0][13] = 0x001E  # KC_1
        keymap[0][14] = 0x002C  # KC_SPC
        keymap[0][15] = 0x7C73  # CW_TOGG
        keymap[0][16] = 0x7C16  # KC_GESC
        keymap[0][17] = 0x00E0  # KC_LCTL
        keymap[1][2] = 0x0006  # KC_C on layer 1
        keymap[1][5] = 0x0001  # KC_TRNS -> TG(1) on layer 0
        keymap[1][6] = 0x0001  # KC_TRNS -> TT(1) on layer 0
        keymap[1][8] = 0x0001  # KC_TRNS -> MO(2) on layer 0
        keymap[2][2] = 0x0008  # KC_E on layer 2
        keymap[3][2] = 0x0007  # KC_D on layer 3
        live = Live(built, keymap=keymap)
        live.run(300)
        self.assertEqual(live.m.gp(929), 8)
        self.assertEqual(live.m.device.values.get(0x8014014C), 0x0B700000)
        self.assertEqual(live.m.device.values.get(0x80140142), 0x80)
        self.assertTrue(any(op == 'w' and addr == 0x80140143 and val == 0x0C
                            for op, _, addr, _, val in live.m.device.log))
        live.take()
        live.event(0, True)
        self.assertEqual(live.take(1)[-1], '0100040000000000')
        live.event(0, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 1a. MT quick tap -> emits KC_A (0x04) then release
        live.event(1, True)
        live.event(1, False)
        reports = live.take(1)
        self.assertIn('0000040000000000', reports)
        self.assertEqual(reports[-1], '0000000000000000')
        # 1b. MT Quick Tap auto-repeat: pressing 1 again within 200ms holds KC_A immediately
        live.event(1, True)
        self.assertEqual(live.take(1)[-1], '0000040000000000')
        live.event(1, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 2a. MT Rolling protection (1 down -> 2 down -> 1 up -> 2 up): emits KC_A then KC_B without Shift
        live.event(1, True)
        live.event(2, True)
        live.event(1, False)
        reports = live.take(1)
        self.assertIn('0000040000000000', reports)
        self.assertEqual(reports[-1], '0000050000000000')
        live.event(2, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 2b. MT Permissive Hold (1 down -> 2 down -> 2 up -> 1 up): nested tap promotes MT to LSFT + KC_B
        live.event(1, True)
        live.event(2, True)
        live.event(2, False)
        reports = live.take(1)
        self.assertIn('0200050000000000', reports)
        self.assertEqual(reports[-1], '0200000000000000')
        live.event(1, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 2c. Reverse rolling (2 down -> 1 down -> 2 up -> 1 up): releasing prior key 2 does NOT promote MT 1
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(1, True)
        live.event(2, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        live.event(1, False)
        reports = live.take(1)
        self.assertIn('0000040000000000', reports)
        self.assertEqual(reports[-1], '0000000000000000')
        live.run(210)
        live.take()
        # 3a. LT quick tap -> emits KC_SPC (0x2C) then release
        live.event(3, True)
        live.event(3, False)
        reports = live.take(1)
        self.assertIn('00002c0000000000', reports)
        self.assertEqual(reports[-1], '0000000000000000')
        # 3b. LT Quick Tap auto-repeat: pressing 3 again within 200ms holds KC_SPC immediately
        live.event(3, True)
        self.assertEqual(live.take(1)[-1], '00002c0000000000')
        live.event(3, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 4. LT + another key press -> promotes LT(1) and resolves key 2 on layer 1 as KC_C (0x06)
        live.event(3, True)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.event(3, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 5. OSL(1) tap -> next key 2 resolves on layer 1 (KC_C = 0x06), subsequent key 2 back on layer 0 (KC_B = 0x05)
        live.event(4, True)
        live.event(4, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 6. TG(1) toggles layer 1 on and off (through KC_TRNS on layer 1)
        live.event(5, True)
        live.event(5, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.take()
        live.event(5, True)
        live.event(5, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 7. MT hold timeout (>200ms without other keys) promotes to pure modifier
        live.event(1, True)
        live.m.cpu.total += (16000 * 210) // 4 + 1
        live.m.call(0x20013DF8)
        live.m.call(0x20012B30)
        self.assertEqual(live.take(1)[-1], '0200000000000000')
        live.event(1, False)
        self.assertEqual(live.take(1)[-1], '0000000000000000')
        # 8. OSL(1) held like MO(1): pressing a key while holding OSL(1) clears oneshot on release
        live.event(4, True)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.event(4, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 9. TT(1): tap toggles layer 1 on/off; hold + key acts as momentary without toggling
        live.event(6, True)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.event(6, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        live.event(6, True)
        live.event(6, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000060000000000')
        live.event(2, False)
        live.take()
        live.event(6, True)
        live.event(6, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 10. FN_MO13 + MO(2) activates Tri-Layer 3 (KC_D = 0x07)
        live.event(7, True)
        live.event(8, True)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000070000000000')
        live.event(2, False)
        live.event(8, False)
        live.event(7, False)
        live.take()
        # 11. DF(2) switches default layer to 2 (KC_E = 0x08); physical OS switch resets DF
        live.event(9, True)
        live.event(9, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000080000000000')
        live.event(2, False)
        live.take()
        live.m.set_gp(130, 1)  # switch to Mac
        live.m.set_gp(130, 0)  # switch back to Win (first event on Mac then Win resets DF)
        live.m.set_gp(130, 1)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000080000000000')
        live.event(2, False)
        live.take()
        live.m.set_gp(130, 0)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 12. Caps Word: Both Shifts (10 + 11) toggles Caps Word on; letters/minus shifted, digits preserved, Space breaks
        live.event(10, True)
        live.event(11, True)
        live.event(10, False)
        live.event(11, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0200050000000000')
        live.event(2, False)
        live.take()
        live.event(12, True)
        self.assertEqual(live.take(1)[-1], '02002d0000000000')
        live.event(12, False)
        live.take()
        live.event(13, True)
        self.assertEqual(live.take(1)[-1], '00001e0000000000')
        live.event(13, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0200050000000000')
        live.event(2, False)
        live.take()
        live.event(14, True)
        self.assertEqual(live.take(1)[-1], '00002c0000000000')
        live.event(14, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        live.event(15, True)
        live.event(15, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0200050000000000')
        live.event(2, False)
        live.take()
        live.event(15, True)
        live.event(15, False)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 12b. Caps Word + Ctrl shortcut: Ctrl+B emits clean Ctrl+B without Shift and exits Caps Word
        live.event(15, True)
        live.event(15, False)
        live.event(17, True)
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0100050000000000')
        live.event(2, False)
        live.event(17, False)
        live.take()
        live.event(2, True)
        self.assertEqual(live.take(1)[-1], '0000050000000000')
        live.event(2, False)
        live.take()
        # 13. MT(MOD_LSFT, KC_A) + KC_GESC within 200ms promotes MT and resolves KC_GESC to Shift + KC_GRV (0x35)
        live.event(1, True)
        live.event(16, True)
        self.assertEqual(live.take(1)[-1], '0200350000000000')
        live.event(16, False)
        live.event(1, False)
        live.take()
        # Verify VIA 0x13 buffer write in RISC-V emulator skips flash program when unchanged
        programs = []
        erases = []
        live.m.stub(0x2000D58C, lambda mm: programs.append((mm.cpu.x[10], mm.cpu.x[11])))
        live.m.stub(0x20008D44, lambda mm: erases.append(mm.cpu.x[10]))
        pkt_addr = 0x80800 + 932
        current_chunk = live.m.bus.peek(0x80800 - 1536, 28)
        packet = bytes([0x13, 0x00, 0x00, 28]) + current_chunk
        live.m.bus.poke(pkt_addr, packet)
        live.m.call(syms['cdb_via_packet'], pkt_addr, sp=0x9FA00)
        self.assertEqual(programs, [])
        self.assertEqual(erases, [])
        # Modify 1 byte on layer 0 and verify exactly 1 flash slot write occurs
        modified = bytearray(current_chunk)
        modified[0] ^= 0xFF
        live.m.bus.poke(pkt_addr, bytes([0x13, 0x00, 0x00, 28]) + bytes(modified))
        live.m.call(syms['cdb_via_packet'], pkt_addr, sp=0x9FA00)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0][1], 256)


if __name__ == '__main__':
    unittest.main()
