#!/usr/bin/env python3
"""Crush 80 wired OTA: inspect, verify, dry-run, or flash explicitly.

Uses the system HIDAPI library (macOS: brew install hidapi). No Python packages.
The firmware is never written by info, verify, list, or dry-run.
"""
import argparse
import ctypes as C
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import zlib

VID, PID, USAGE, REPORT = 0x320f, 0x5055, 0xffef, 5
PACKET_SIZE = 64  # Verified descriptor: report 5, 63 bytes payload.

# Historical unsafe images are refused by content hash so renamed files cannot
# bypass the guard accidentally.
UNSAFE_IMAGES = {
    '960b6a9b184cd10cace235355da0d1dcc948c9421902a823f32596992f315d67':
        'V4 modifies the wired RGB task gate without a proven state model',
    '7a20e6d095aec5e4bb9138d041f64475b4e1131bc417b80a2cde8b1724227670':
        'V5 calls RGB initialization from an unverified lifecycle point',
    '16c5a4510ab9def2e39e2ea82349479705932c0a21a7138ab0e51e14c0e551ab':
        'V6 enters the RGB routine after its stack allocation instruction',
    '74c93a6c8d0f64d79d099d51db9d9022852dd74346e6a227fbc2faa923ad0339':
        'V7 caused the tested keyboard to stop enumerating',
}
APPROVED_FLASH_IMAGES = {
    'b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da':
        {'name': 'official WOBLAB RGB 20260618', 'crc': 0xCA2D85DC,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
    '7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88':
        {'name': '20260618 Mac-layers RC2', 'crc': 0xFE1AA4C2,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
    '7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35':
        {'name': '20261021 NativeHeld preview', 'crc': 0x350AD5C5,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x54AB7AC3, 0xDCA8651C, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
    '46c51d50748dcef47c0e1bf2b0460bf2441e626ed8f4cf73eec2498ce6c363d0':
        {'name': '20261031 NativeHeld refactored', 'crc': 0x239D8875,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x54AB7AC3, 0xDCA8651C, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
    '000aaac1de73802f784f92df4b51bd35c5015adff3be869deacbb4b5d1cf20f0':
        {'name': '20261101 NativeHeld QMK/VIA layers + Tap-Hold', 'crc': 0x1BF4AA83,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x54AB7AC3, 0xDCA8651C, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
    '68bb25b07e3c047a60e606410723977f9b689d9131393be5d3a8c5a0ed778ca4':
        {'name': '20261101 NativeHeld QMK/VIA + Watchdog', 'crc': 0x13DADB12,
         'from_crcs': (0xCA2D85DC, 0xFE1AA4C2, 0x54AB7AC3, 0xDCA8651C, 0x350AD5C5, 0x239D8875, 0x1BF4AA83, 0x13DADB12)},
}

def reject_unsafe_image(image):
    digest = hashlib.sha256(image).hexdigest()
    reason = UNSAFE_IMAGES.get(digest)
    if reason:
        raise ValueError(f'Known-unsafe firmware refused ({digest}): {reason}')
    if digest not in APPROVED_FLASH_IMAGES:
        raise ValueError(f'Unreviewed firmware refused ({digest}). '
                         'This flasher only writes an exact allowlisted image.')
    policy = APPROVED_FLASH_IMAGES[digest]
    if int.from_bytes(image[-4:], 'little') != policy['crc']:
        raise ValueError('Allowlisted image has an unexpected embedded CRC')
    return digest

def validate_flash_transition(image_digest, current_crc):
    policy = APPROVED_FLASH_IMAGES[image_digest]
    allowed = policy['from_crcs']
    if allowed is not None and current_crc not in allowed:
        expected = ', '.join(f'{value:08x}' for value in allowed)
        raise RuntimeError(f"{policy['name']} may only be installed from CRC: {expected}; "
                           f'device reports {current_crc:08x}')
    return policy['name']

def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc

def load_image(path):
    raw = Path(path).read_bytes()
    if len(raw) == 2097152 and raw[288:292] == b'KNLT':
        size = int.from_bytes(raw[48:52], 'big')
        if not 40 <= size <= len(raw)-256:
            raise ValueError('Invalid outer image size')
        raw = raw[256:256+size]
    if len(raw) < 40 or raw[32:36] != b'KNLT':
        raise ValueError('Not a raw Telink image or code_2M container')
    if int.from_bytes(raw[24:28], 'little') != len(raw):
        raise ValueError('Internal size mismatch; refusing truncated/padded image')
    if len(raw) != 124436:
        raise ValueError('Only the examined Crush 80 RGB 20260618 image size is supported')
    if zlib.crc32(raw) != 0xffffffff:
        raise ValueError('CRC mismatch; refusing firmware')
    return raw

def packet(payload):
    if len(payload) > 63:
        raise ValueError('Oversized OTA payload')
    return bytes([REPORT]) + payload + b'\xff'*(63-len(payload))

def packets(image):
    count = (len(image)+15)//16
    padded = image + b'\xff'*(count*16-len(image))
    yield 'start', packet(bytes.fromhex('02020001ff'))
    for first in range(0, count, 3):
        chunks = []
        for index in range(first, min(first+3, count)):
            chunk = struct.pack('<H', index) + padded[index*16:index*16+16]
            chunks.append(chunk + struct.pack('<H', crc16(chunk)))
        data = b''.join(chunks)
        yield f'data:{first}', packet(bytes([2, len(data), 0])+data)
    last = count-1
    # This is TWO'S complement, verified in the stock C# ota_write().
    yield 'end', packet(bytes.fromhex('02060002ff') + struct.pack('<HH', last, (-last)&0xffff))

def parse_response(data):
    if len(data) < 4 or data[0] != REPORT:
        raise ValueError(f'Malformed HID response: {data.hex()}')
    size = int.from_bytes(data[2:4], 'little')
    if size > 60 or len(data) < 4+size:
        raise ValueError(f'Malformed OTA length: {data.hex()}')
    if data[:6] == bytes.fromhex('0502030006ff'):
        return 'result', data[6]
    if data[:4] == bytes.fromhex('05010800'):
        return 'info', struct.unpack_from('<II', data, 4)
    if data[1] == 2:
        # Exact nonterminal ACK semantics are not documented. Like the stock
        # updater, use an OTA response as pacing, but reject malformed/non-OTA
        # reports and explicit errors. Do not call this firmware verification.
        return 'ota', data[4:4+size]
    raise ValueError(f'Unexpected response type: {data.hex()}')

class DeviceInfo(C.Structure):
    pass

DeviceInfo._fields_ = [
    ('path', C.c_char_p), ('vendor_id', C.c_ushort), ('product_id', C.c_ushort),
    ('serial_number', C.c_wchar_p), ('release_number', C.c_ushort),
    ('manufacturer_string', C.c_wchar_p), ('product_string', C.c_wchar_p),
    ('usage_page', C.c_ushort), ('usage', C.c_ushort), ('interface_number', C.c_int),
    ('next', C.POINTER(DeviceInfo)),
]

class HID:
    def __init__(self):
        names = [os.environ.get('CRUSH80_HIDAPI_LIBRARY')]
        names += [C.util.find_library(n) for n in ('hidapi-hidraw', 'hidapi')]
        names += ['/opt/homebrew/lib/libhidapi.dylib', '/usr/local/lib/libhidapi.dylib',
                  'libhidapi-hidraw.so.0', 'hidapi.dll']
        self.lib = None
        for name in filter(None, names):
            try:
                self.lib = C.CDLL(name)
                break
            except OSError:
                continue
        if self.lib is None:
            raise RuntimeError('HIDAPI not found. macOS: brew install hidapi. '
                               'Or set CRUSH80_HIDAPI_LIBRARY to the library path.')
        defs = {
            'hid_init': (C.c_int, []), 'hid_exit': (C.c_int, []),
            'hid_enumerate': (C.POINTER(DeviceInfo), [C.c_ushort, C.c_ushort]),
            'hid_free_enumeration': (None, [C.POINTER(DeviceInfo)]),
            'hid_open_path': (C.c_void_p, [C.c_char_p]),
            'hid_close': (None, [C.c_void_p]),
            'hid_write': (C.c_int, [C.c_void_p, C.c_void_p, C.c_size_t]),
            'hid_read_timeout': (C.c_int, [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int]),
            'hid_error': (C.c_wchar_p, [C.c_void_p]),
        }
        for name, (restype, args) in defs.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, args
        if self.lib.hid_init() != 0:
            raise RuntimeError('hid_init failed')
        if hasattr(self.lib, 'hid_darwin_set_open_exclusive'):
            fn = self.lib.hid_darwin_set_open_exclusive
            fn.argtypes, fn.restype = [C.c_int], None
            fn(0)
        self.handle = None

    def enumerate(self):
        head = self.lib.hid_enumerate(VID, 0)
        cur, result = head, []
        try:
            while cur:
                d = cur.contents
                result.append(dict(path=bytes(d.path), pid=d.product_id,
                                   usage=d.usage_page, interface=d.interface_number,
                                   product=d.product_string, release=d.release_number))
                cur = d.next
        finally:
            self.lib.hid_free_enumeration(head)
        return result

    def open(self):
        devices = [d for d in self.enumerate() if d['pid'] == PID and d['usage'] == USAGE]
        if len(devices) != 1:
            raise RuntimeError(f'Expected exactly one wired Crush 80 OTA interface; found {len(devices)}. '
                               'Connect by USB cable and select wired mode. Dongle OTA is not supported.')
        self.handle = self.lib.hid_open_path(devices[0]['path'])
        if not self.handle:
            raise RuntimeError('Cannot open OTA interface: '+str(self.lib.hid_error(None)))
        return devices[0]

    def write(self, data):
        buf = C.create_string_buffer(data)
        n = self.lib.hid_write(self.handle, buf, len(data))
        if n != len(data):
            raise OSError(f'HID write {n}/{len(data)}: {self.lib.hid_error(self.handle)}')

    def read(self, timeout_ms):
        buf = C.create_string_buffer(PACKET_SIZE)
        n = self.lib.hid_read_timeout(self.handle, buf, PACKET_SIZE, timeout_ms)
        if n < 0:
            raise OSError('HID read: '+str(self.lib.hid_error(self.handle)))
        return buf.raw[:n]

    def close(self):
        if self.handle:
            self.lib.hid_close(self.handle)
            self.handle = None

    def shutdown(self):
        self.close()
        self.lib.hid_exit()

class Session:
    def __init__(self, dev, log=None):
        self.dev, self.log = dev, log

    def record(self, direction, data):
        if self.log:
            self.log.write(json.dumps(dict(time=time.time(), direction=direction, hex=data.hex()))+'\n')
            self.log.flush()

    def send(self, data):
        self.record('tx', data)
        self.dev.write(data)

    def receive(self, timeout=5000):
        data = self.dev.read(timeout)
        if not data:
            raise TimeoutError('No device response; update is NOT confirmed')
        self.record('rx', data)
        return parse_response(data)

    def info(self):
        # Query only; does not enter OTA mode.
        self.send(packet(bytes.fromhex('010000')))
        kind, value = self.receive()
        if kind != 'info':
            raise RuntimeError(f'Expected version/CRC response, received {kind}')
        return value

def transfer(session, image):
    for phase, data in packets(image):
        session.send(data)
        kind, value = session.receive(10000)
        if kind == 'result' and value != 0:
            raise RuntimeError(f'Device rejected {phase}: OTA error {value}')
        if phase == 'end':
            if kind != 'result' or value != 0:
                raise RuntimeError('No explicit final OTA success; query CRC after reconnecting')
        elif kind != 'ota':
            raise RuntimeError(f'Unexpected {kind} during {phase}; aborting')
        if phase.startswith('data:'):
            index = int(phase.split(':')[1])
            if index % 300 == 0:
                print(f'  Sent {min(index+3, (len(image)+15)//16)} / {(len(image)+15)//16} chunks', flush=True)

def wait_for_crc(hid, expected, log):
    hid.close()
    deadline = time.monotonic()+20
    last_error = 'No query completed'
    # Require a fresh handle, and allow the keyboard to finish its restart.
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            hid.open()
            _, crc = Session(hid, log).info()
            if crc == expected:
                return
            last_error = f'CRC {crc:08x}, expected {expected:08x}'
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            last_error = str(exc)
        finally:
            hid.close()
    raise RuntimeError('Post-restart CRC not verified: '+last_error+
                       '. Reconnect the cable and use verify; do not automatically reflash.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'info', 'verify', 'dry-run', 'flash'])
    parser.add_argument('image', nargs='?')
    parser.add_argument('--yes', action='store_true', help='Explicitly authorize firmware overwrite')
    parser.add_argument('--force', action='store_true',
                        help='Flash even when the device already reports this image CRC')
    parser.add_argument('--log', type=Path, help='JSONL trace (created exclusively, never overwritten)')
    args = parser.parse_args()
    image = None
    if args.command in ('verify', 'dry-run', 'flash'):
        if not args.image:
            parser.error('image is required')
        image = load_image(args.image)
        if args.command == 'flash':
            image_digest = reject_unsafe_image(image)
        expected = int.from_bytes(image[-4:], 'little')
        print(f'Image: {len(image)} bytes, CRC {expected:08x}')
    if args.command == 'dry-run':
        all_packets = list(packets(image))
        print(f'{len(all_packets)} HID writes; all exactly 64 bytes')
        for phase, data in (all_packets[0], all_packets[1], all_packets[-2], all_packets[-1]):
            print(phase, data.hex(' '))
        return
    if args.command == 'flash' and not args.yes:
        parser.error('Use --yes to authorize writing this image. Save your VIA layout first.')
    log_path = args.log
    if args.command == 'flash' and log_path is None:
        log_path = Path('crush80-ota-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')
    log = log_path.open('x') if log_path else None
    hid = None
    try:
        hid = HID()
        if args.command == 'list':
            for d in hid.enumerate():
                print(f"PID={d['pid']:04x} usage={d['usage']:04x} interface={d['interface']} "
                      f"release={d['release']:04x} {d['product']} {d['path'].decode(errors='replace')}")
            return
        device = hid.open()
        print(f"Wired device: {device['product']}, USB release {device['release']:04x}")
        session = Session(hid, log)
        version, current_crc = session.info()
        print(f'Device version={version:08x} CRC={current_crc:08x}')
        if args.command == 'info':
            return
        if args.command == 'verify':
            if current_crc != expected:
                raise RuntimeError(f'Device CRC does not match image: expected {expected:08x}')
            print('Device-reported CRC matches image. Physical key behavior still requires testing.')
            return
        image_name = validate_flash_transition(image_digest, current_crc)
        if current_crc == expected and not args.force:
            print('Device already reports the requested CRC; no firmware written.')
            return
        print(f'OTA trace: {log_path}', flush=True)
        try:
            transfer(session, image)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            print(f'OTA did not complete cleanly: {exc}', file=sys.stderr)
            print('Checking device-reported CRC; no further firmware writes.', flush=True)
            wait_for_crc(hid, expected, log)
        else:
            print('OTA success response received. Verifying after restart...', flush=True)
            wait_for_crc(hid, expected, log)
        print('VERIFIED: device reports the requested image CRC on a fresh connection.')
    finally:
        if hid:
            hid.shutdown()
        if log:
            log.close()

if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nInterrupted; firmware status unconfirmed. Query CRC after reconnecting.', file=sys.stderr)
        sys.exit(130)
