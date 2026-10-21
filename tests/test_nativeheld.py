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
from build_nativeheld import OUTPUT_SHA256, assemble, load_plan
from nativeheld.elf_layout import sections
from nativeheld.trns import patch as trns_patch
from test_firmware import load_tool


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


if __name__ == '__main__':
    unittest.main()
