"""Cold start, timer interrupt and wake models around the real startup code.

`Machine` normally begins from the RAM that cold startup produces.  Here the
ILM code is loaded the way the boot ROM leaves it, the DLM is filled with
arbitrary bytes, and execution starts at address 0, so the image's own
startup code copies .data, zeroes .bss and runs the init path up to the main
loop.  Everything outside the image is a model with explicit assumptions:

* analog register bus (0x80140180..): a plain register file.  A register that
  is polled many times in a row alternates 0xFF/0x00 so waits on either
  polarity terminate.  Values written by firmware are kept (this is what
  survives a deep sleep on hardware); reset values are 0 unless supplied.
* flash JEDEC id (stub of RAM routine 0x20009BE4: capacity byte 0x14) and
  the status polls at 0x8014020B and 0x80101808 are reported ready.
* 1 ms timer interrupt: before each slice the interrupt is delivered
  (mtvec[3] -> RAM 0x2B80) only if mstatus.MIE is set, and runs to its mret;
  interrupts do not nest.  One slice is 4000 steps = 1 ms at TICKS_PER_STEP=4.
* the matrix scan (RAM 0x30BC) is stubbed in `Live`; key events are injected
  with dispatch calls like `Keyboard` does.
* deep sleep is modelled as a cold start that keeps only the analog file; its
  entry conditions were not reproduced (the idle gating in main was not
  decoded), only the reboot.  Suspend is modelled as READY (gp+929) = 0, which
  is what the sleep entry at RAM 0x42A4 does, followed by normal ticks.

These are not measurements of TLSR9511 and prove nothing about timing.
"""
import collections

from .cpu import Halt
from .keyboard import DELAY_MS, DELAY_US, USB_ENDPOINT_WRITE, Keyboard
from .machine import Machine

MAIN_LOOP = 0x4050
STEPS_PER_MS = 4000


class AnalogBus:
    def __init__(self, machine, regs=None):
        self.regs, self.addr, self.len = dict(regs or {}), 0, 1
        self.buf, self.last, self.polls, self.log = bytearray(4), None, 0, []
        device, original = machine.device, machine.device.write

        def write(address, size, value, pc):
            original(address, size, value, pc)
            if address == 0x80140180:
                self.addr = value & 0xFF
            elif address == 0x80140183:
                self.len = value & 0xFF or 1
            elif 0x80140184 <= address <= 0x80140187:
                for i in range(size):
                    self.buf[address - 0x80140184 + i] = (value >> (8 * i)) & 0xFF
            elif address == 0x80140182 and value & 0x40:
                if value & 0x20:
                    for i in range(self.len):
                        self.regs[self.addr + i] = self.buf[i]
                        self.log.append(('w', self.addr + i, self.buf[i]))
                else:
                    key = (self.addr, self.len)
                    self.polls = self.polls + 1 if key == self.last else 1
                    self.last = key
                    for i in range(min(self.len, 4)):
                        current = self.regs.get(self.addr + i, 0)
                        if self.polls > 40:
                            current = 0xFF if (self.polls // 40) % 2 else 0x00
                        self.buf[i] = current
                    self.log.append(('r', self.addr, self.len))
                device.values[0x80140182] = 0      # never busy
        device.write = write
        device.readers[0x80140184] = lambda size: int.from_bytes(bytes(self.buf[:size]), 'little')
        for i in range(1, 4):
            device.readers[0x80140184 + i] = \
                (lambda i: lambda size: int.from_bytes(bytes(self.buf[i:i + size]), 'little'))(i)


def new_machine(image, garbage=0xA5, analog=None):
    m = Machine(image)
    dlm = m.bus.ram[1]
    dlm.data[:] = bytes([garbage]) * len(dlm.data)
    dlm.valid[:] = bytes(len(dlm.valid))
    m.bus.uninitialised_reads.clear()
    m.cpu.x[:] = [0] * 32
    m.cpu.pc = 0
    m.cpu.csr[0x300] = 0
    m.device.WINDOWS += ((0x80000000, 0x80100000), (0x80200000, 0x80300000))
    m.device.readers[0x8014020B] = lambda size: 0xFF
    m.device.readers[0x80101808] = lambda size: 0xFF
    m.stub(0x20009BE4, lambda mm: 0x00146085)
    return m, AnalogBus(m, analog)


def coldboot(image, garbage=0xA5, analog=None, steps=4_000_000, iterations=3):
    """Run startup until the main loop was entered `iterations` times."""
    m, analog_bus = new_machine(image, garbage, analog)
    visits = [0]

    def trace(cpu, pc, op):
        if pc == MAIN_LOOP:
            visits[0] += 1
            if visits[0] >= iterations:
                raise StopIteration
    m.cpu.trace = trace
    try:
        m.cpu.run(steps)
    except StopIteration:
        pass
    finally:
        m.cpu.trace = None
    return m, analog_bus


def deliver_timer(m, handler=0x2B80):
    c = m.cpu
    if not c.csr[0x300] & 8:
        return
    saved = (list(c.x), c.pc, dict(c.csr))
    m.device.values[0x80140143] = m.device.values.get(0x80140143, 0) | 2
    c.csr[0x341] = c.pc
    c.csr[0x300] = (c.csr[0x300] & ~8) | ((c.csr[0x300] & 8) << 4)
    c.pc = handler
    try:
        c.run(c.steps + 20000)
    except Halt as stop:
        if str(stop) != 'mret':
            raise
    c.x[:], c.pc = saved[0], saved[1]
    c.csr.clear()
    c.csr.update(saved[2])


def run_ms(m, ms):
    c = m.cpu
    for _ in range(ms):
        c.steps = 0
        try:
            c.run(STEPS_PER_MS)
        except RuntimeError as error:
            if 'step limit' not in str(error):
                raise
        deliver_timer(m)


class Live:
    """A cold-booted machine; harness key events run between main-loop slices."""

    def __init__(self, image, keymap=None, garbage=0xA5, analog=None):
        self.m, self.analog = coldboot(image, garbage, analog)
        m = self.m
        keyboard = Keyboard.__new__(Keyboard)
        keyboard.machine, keyboard.reports, keyboard.macro_flash = m, [], None
        m.stub(USB_ENDPOINT_WRITE, keyboard._endpoint)
        m.stub(DELAY_MS, lambda mm: keyboard._wait(mm, 16000))
        m.stub(DELAY_US, lambda mm: keyboard._wait(mm, 16))
        m.stub(0x30BC, lambda mm: 0)
        self.keyboard = keyboard
        if keymap is not None:
            m.bus.poke(0x80800 - 1536, b''.join(c.to_bytes(2, 'big') for layer in keymap for c in layer))

    def run(self, ms):
        run_ms(self.m, ms)

    def event(self, position, down):
        c = self.m.cpu
        saved = (list(c.x), c.pc, dict(c.csr), c.steps)
        self.keyboard.key(position, down)
        c.x[:], c.pc, c.steps = saved[0], saved[1], saved[3]
        c.csr.clear()
        c.csr.update(saved[2])

    def take(self, endpoint=None):
        return [data for ep, data, _ in self.keyboard.take() if endpoint in (None, ep)]
