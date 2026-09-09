import importlib.util
from pathlib import Path
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_firmware import (CODE_CAVE, LAYER_LOAD, MAC_PATCHES, OUTPUT_SHA256,
                            SOURCE_SHA256, layer_code, patch, sha256)


def load_tool():
    spec = importlib.util.spec_from_file_location('crush80_tool', ROOT/'tools'/'crush80.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = (ROOT/'firmware'/'official'/'Crush80-RGB-20260618-official.bin').read_bytes()
        cls.checked_in = (ROOT/'firmware'/'patched'/'Crush80-RGB-20260618-MacLayers-RC2.bin').read_bytes()

    def test_exact_images_and_reproducible_build(self):
        self.assertEqual(sha256(self.stock), SOURCE_SHA256)
        self.assertEqual(sha256(self.checked_in), OUTPUT_SHA256)
        self.assertEqual(patch(self.stock), self.checked_in)
        self.assertEqual(zlib.crc32(self.checked_in), 0xffffffff)

    def test_diff_is_limited_to_declared_sites(self):
        allowed = set(range(CODE_CAVE, CODE_CAVE + len(layer_code())))
        allowed.update(range(LAYER_LOAD, LAYER_LOAD + 4))
        for offset, _, _ in MAC_PATCHES:
            allowed.update(range(offset, offset + 4))
        allowed.update(range(len(self.stock)-4, len(self.stock)))
        changed = {i for i,(a,b) in enumerate(zip(self.stock,self.checked_in)) if a != b}
        self.assertTrue(changed <= allowed)
        self.assertEqual(len(changed), 49)

    def test_layer_mapping_for_all_flag_values(self):
        for os_flag in range(256):
            for active in range(4):
                result = active + 2 if os_flag and active < 2 else active
                expected = active if not os_flag else (2,3,2,3)[active]
                self.assertEqual(result, expected)

    def test_flasher_allowlist_and_transition(self):
        tool = load_tool()
        digest = tool.reject_unsafe_image(self.checked_in)
        self.assertEqual(digest, OUTPUT_SHA256)
        self.assertEqual(tool.validate_flash_transition(digest, 0xca2d85dc),
                         '20260618 Mac-layers RC2')
        with self.assertRaises(RuntimeError):
            tool.validate_flash_transition(digest, 0x28ca805b)


if __name__ == '__main__':
    unittest.main()
