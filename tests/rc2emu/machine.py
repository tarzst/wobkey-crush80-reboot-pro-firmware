"""Memory map and call harness around `cpu.CPU` for the pinned RC2 image.

Initial RAM is exactly what cold startup produces from the image (copies and
zero fills, from `audit_event_path.audit`).  Everything else is marked
uninitialised and every read of it is recorded, so missing harness state is
visible instead of silently zero.  Peripheral accesses are recorded and
answered by an explicit device model; an access outside every modelled
region is an error.
"""
import hashlib
from pathlib import Path

from .cpu import CPU, Halt, MASK, sext

ROOT = Path(__file__).resolve().parent.parent.parent
RC2 = ROOT / 'firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin'
ACCEPTED = {
    'b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da': 'official-0108',
    '7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88': 'rc2',
}
XIP = 0x20000000
ILM = (0x00000, 0x20000)
DLM = (0x80000, 0xA0000)
GP = 0x80800
RETURN = 0xFFFFFFF0
SYSTEM_TIMER = 0x80140200
TICKS_PER_STEP = 4


def startup_address(image, offset, *, instruction_address=None):
    """Evaluate a checked AUIPC/ADDI pair at its actual execution address."""
    if offset < 0 or offset + 8 > len(image):
        raise ValueError(f'truncated AUIPC/ADDI pair at {offset:#x}')
    word = int.from_bytes(image[offset:offset + 4], 'little')
    following = int.from_bytes(image[offset + 4:offset + 8], 'little')
    rd = (word >> 7) & 31
    if (word & 0x7F != 0x17 or following & 0x707F != 0x13 or
            (following >> 7) & 31 != rd or (following >> 15) & 31 != rd):
        raise ValueError(f'expected AUIPC/ADDI pair at {offset:#x}')
    pc = XIP + offset if instruction_address is None else instruction_address
    return (pc + (word & 0xFFFFF000) + sext(following >> 20, 12)) & 0xFFFFFFFF


def startup_metadata(image):
    digest = hashlib.sha256(image).hexdigest()
    if digest not in ACCEPTED:
        raise ValueError('not the pinned official 0108 image or RC2')
    segments = []
    for src, dst, end in ((0x8E, 0x96, 0x9E), (0xB8, None, 0xC4),
                          (0xDE, 0xE6, 0xEE), (0x108, 0x110, 0x118)):
        destination = startup_address(image, dst) if dst is not None else 0x178
        limit = startup_address(image, end)
        segments.append(dict(source=startup_address(image, src),
                             destination=destination, limit=limit,
                             written_end=destination + ((limit - destination + 3) // 4) * 4))
    return dict(
        copy_segments=segments,
        zero_segments=[
            dict(start=startup_address(image, 0x136), end=startup_address(image, 0x13E)),
            dict(start=startup_address(image, 0x156), end=startup_address(image, 0x15E)),
        ],
    )


class Fault(Exception):
    pass


class Region:
    def __init__(self, start, end, writable, name):
        self.start, self.end, self.writable, self.name = start, end, writable, name
        self.data = bytearray(end - start)
        self.valid = bytearray(end - start)

    def fill(self, address, payload):
        offset = address - self.start
        self.data[offset:offset + len(payload)] = payload
        self.valid[offset:offset + len(payload)] = b'\1' * len(payload)


class Bus:
    def __init__(self, image, device, startup_reference=None):
        self.image = image
        self.device = device
        self.ram = [Region(*ILM, True, 'ilm'), Region(*DLM, True, 'dlm')]
        self.uninitialised_reads = {}
        self.misaligned = set()
        self.watch = None
        metadata = startup_metadata(startup_reference or image)
        for segment in metadata['copy_segments']:
            source = segment['source'] - XIP
            length = segment['written_end'] - segment['destination']
            self.load(segment['destination'], image[source:source + length])
        # First copy maps file [0x190, 0x2e8) to RAM [0, 0x158); see audit().
        self.load(0, image[0x190:0x190 + 0x158])
        for zero in metadata['zero_segments']:
            self.load(zero['start'], bytes(zero['end'] - zero['start']))

    def region(self, address, size):
        for region in self.ram:
            if region.start <= address and address + size <= region.end:
                return region
        return None

    def load(self, address, payload):
        region = self.region(address, len(payload))
        if region is None:
            raise Fault(f'load outside RAM {address:#x}+{len(payload)}')
        region.fill(address, payload)

    def fetch16(self, address):
        if XIP <= address and address + 2 <= XIP + len(self.image):
            offset = address - XIP
            return self.image[offset] | self.image[offset + 1] << 8
        region = self.region(address, 2)
        if region is None or region.name != 'ilm':
            raise Fault(f'instruction fetch outside XIP/ILM at {address:#x}')
        offset = address - region.start
        if not all(region.valid[offset:offset + 2]):
            raise Fault(f'fetch of uninitialised ILM at {address:#x}')
        return region.data[offset] | region.data[offset + 1] << 8

    def misaligned_ok(self, address, size, pc, region):
        # RC2 itself issues misaligned RAM accesses (first seen: halfword
        # store to the consumer report 0x80B19 at 0x20008F78), so the core
        # must support them for RAM.  They are recorded; MMIO stays strict.
        if address % size:
            if region is None:
                raise Fault(f'misaligned {size}-byte access {address:#x} at {pc:#x}')
            self.misaligned.add((pc, address, size))

    def read(self, address, size, pc):
        region = self.region(address, size)
        self.misaligned_ok(address, size, pc, region)
        if region is not None:
            offset = address - region.start
            if not all(region.valid[offset:offset + size]):
                self.uninitialised_reads.setdefault(address, pc)
            return int.from_bytes(region.data[offset:offset + size], 'little')
        if XIP <= address and address + size <= XIP + len(self.image):
            offset = address - XIP
            return int.from_bytes(self.image[offset:offset + size], 'little')
        return self.device.read(address, size, pc)

    def write(self, address, size, value, pc):
        region = self.region(address, size)
        self.misaligned_ok(address, size, pc, region)
        value &= (1 << (8 * size)) - 1
        if region is not None:
            offset = address - region.start
            region.data[offset:offset + size] = value.to_bytes(size, 'little')
            region.valid[offset:offset + size] = b'\1' * size
            if self.watch is not None:
                self.watch(address, size, value, pc)
            return
        if XIP <= address < XIP + 0x1000000:
            raise Fault(f'write to flash window {address:#x} at {pc:#x}')
        self.device.write(address, size, value, pc)

    def peek(self, address, size):
        region = self.region(address, size)
        offset = address - region.start
        return bytes(region.data[offset:offset + size])

    def poke(self, address, payload):
        self.load(address, bytes(payload))


class Device:
    """Peripheral windows, recorded; reads return the last written value or 0.

    0x80100000..0x80200000: SoC registers (timer, MSPI flash controller...).
    0xE4000000..0xE4400000: Andes PLIC; RC2 writes the threshold 0xE4200000
    around flash commands (e.g. RAM 0x12CC, 0x1524).  With reads of 0 the
    MSPI busy bit (0x80140102 bit 0) is clear, so flash commands complete
    without effect; their register writes stay in `log` for comparison.
    This is not a flash model.
    """

    WINDOWS = ((0x80100000, 0x80200000), (0xE4000000, 0xE4400000))

    def __init__(self):
        self.log = []
        self.values = {}
        self.readers = {}

    def check(self, address, size, pc):
        if not any(start <= address and address + size <= end for start, end in self.WINDOWS):
            raise Fault(f'access outside modelled memory {address:#x}+{size} at {pc:#x}')

    def read(self, address, size, pc):
        self.check(address, size, pc)
        reader = self.readers.get(address)
        value = reader(size) if reader else self.values.get(address, 0)
        self.log.append(('r', pc, address, size, value))
        return value & ((1 << (8 * size)) - 1)

    def write(self, address, size, value, pc):
        self.check(address, size, pc)
        self.values[address] = value
        self.log.append(('w', pc, address, size, value))


def check_derived(reference, image):
    """Accept a patched RC2 only if cold startup is byte-identical.

    Every changed byte must lie outside the startup copy sources (and the
    header), so the RC2 copy/zero metadata describes the patched image too.
    """
    if len(image) != len(reference):
        raise ValueError('derived image must keep the RC2 length')
    metadata = startup_metadata(reference)
    copied = [(0, 0x2E8)] + [(s['source'] - XIP, s['source'] - XIP + s['written_end'] - s['destination'])
                             for s in metadata['copy_segments']]
    for offset in range(len(image) - 4):
        if image[offset] != reference[offset] and any(a <= offset < b for a, b in copied):
            raise ValueError(f'derived image changes startup-copied byte {offset:#x}')


class Machine:
    def __init__(self, image=None):
        image = image if image is not None else RC2.read_bytes()
        reference = None
        if hashlib.sha256(image).hexdigest() not in ACCEPTED:
            reference = RC2.read_bytes()
            check_derived(reference, image)
        self.device = Device()
        self.bus = Bus(image, self.device, reference)
        self.cpu = CPU(self.bus)
        self.cpu.x[3] = GP
        self.cpu.x[2] = DLM[1]
        self.cpu.csr[0x300] = 0
        self.cpu.hooks[RETURN] = self._returned
        self.max_depth = {}
        # System timer 0x80140200, read by delay loops such as RAM 0x14E4
        # (a0 ms = a0 * 16000 ticks).  Model: TICKS_PER_STEP ticks per
        # executed instruction, i.e. a fixed instruction rate, not a
        # measured TLSR9511 timing.
        self.device.readers[SYSTEM_TIMER] = lambda size: self.ticks()
        # Flash command at RAM 0x1564 polls 0x80140328 bit 3 before issuing
        # the MSPI command; report it ready.  Assumption, not a measured value.
        self.device.readers[0x80140328] = lambda size: 0x08

    def ticks(self):
        return (self.cpu.total * TICKS_PER_STEP) & MASK

    def milliseconds(self):
        return self.ticks() / 16000

    @staticmethod
    def _returned(cpu):
        raise Halt('return')

    def gp(self, offset, size=1):
        return int.from_bytes(self.bus.peek(GP + offset, size), 'little')

    def set_gp(self, offset, value, size=1):
        self.bus.poke(GP + offset, (value & ((1 << 8 * size) - 1)).to_bytes(size, 'little'))

    def call(self, address, *args, limit=200000, sp=None):
        cpu = self.cpu
        for index, value in enumerate(args):
            cpu.x[10 + index] = value & MASK
        cpu.x[1] = RETURN
        if sp is not None:
            cpu.x[2] = sp
        start_sp = cpu.x[2]
        cpu.min_sp = start_sp
        cpu.pc = address
        cpu.steps = 0
        try:
            cpu.run(limit)
        except Halt as stop:
            if str(stop) != 'return':
                raise
        if cpu.x[2] != start_sp:
            raise Fault(f'sp not restored: {start_sp:#x} -> {cpu.x[2]:#x}')
        depth = start_sp - cpu.min_sp
        self.max_depth[address] = max(self.max_depth.get(address, 0), depth)
        return cpu.x[10]

    def stub(self, address, function):
        """Replace the function at `address`; `function(machine)` returns a0."""
        def hook(cpu):
            result = function(self)
            if result is not None:
                cpu.x[10] = result & MASK
            cpu.pc = cpu.x[1]
        self.cpu.hooks[address] = hook
