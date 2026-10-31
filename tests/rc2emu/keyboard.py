"""Keyboard-level harness: real RC2 matrix dispatch and USB sender.

What runs as RC2 code: matrix dispatch 0x200130B8 (and everything it calls),
the transport selector 0x20012B30, the USB report sender 0x2001B624 and the
macro interpreter 0x20013DF8.  What the harness provides:

* matrix input: the state byte per column that dispatch reads
  (gp+4856 when gp+133 == 0, gp+4904 otherwise; see 0x200130EE/0x20013544);
* the USB endpoint write 0x2000CC30 is replaced by a capture that reports
  success; its arguments are (endpoint, buffer, length) at every call site
  in 0x2001B624;
* main-loop timing: `idle()` runs the sender and the macro interpreter and
  decrements the macro delay gp+394 as the timer ISR does at 0x3606..0x362C;
* state that main() would establish: readiness gp+929 = 8 (0x1ADDA) and the
  keymap tables gp-1536.. in VIA big-endian order (lookup 0x20013240).

Everything else starts from the image's cold-startup RAM.
"""
from .machine import GP, TICKS_PER_STEP, Machine

DISPATCH = 0x200130B8
SELECT_SENDER = 0x20012B30
USB_ENDPOINT_WRITE = 0x2000CC30
MACRO_INTERPRETER = 0x20013DF8
DELAY_MS = 0x14E4
DELAY_US = 0x1508
KEYMAP = GP - 1536
MACROS_RAM = GP + 996          # interpreter reads 512 bytes into here (0x13E3E)
COLUMNS = 16


class Keyboard:
    def __init__(self, keymap, macros=None, image=None, debounced=False, mac=False,
                 fast_delay=False):
        self.machine = m = Machine(image)
        self.reports = []
        m.bus.poke(KEYMAP, b''.join(code.to_bytes(2, 'big')
                                    for layer in keymap for code in layer))
        m.set_gp(929, 8)
        if debounced:
            m.set_gp(133, 1)
        if mac:
            m.set_gp(130, 1)            # Win/Mac flag read by the RC2 hook 0x10AC
        if fast_delay:
            # Busy wait RAM 0x14E4(a0 ms): advance the modelled timer instead
            # of executing a0 * 16000 / TICKS_PER_STEP loop iterations.
            m.stub(DELAY_MS, lambda mm: self._wait(mm, 16000))
            m.stub(DELAY_US, lambda mm: self._wait(mm, 16))
        m.stub(USB_ENDPOINT_WRITE, self._endpoint)
        self.macro_flash = macros
        if macros is not None:
            m.stub(0x2000D510, self._flash_read)

    def _wait(self, m, ticks_per_unit):
        """Busy waits RAM 0x14E4 (ms) and 0x1508 (us), same register results
        as the loops: a0 = limit, a3 = start tick, a4 = 0x80140000,
        a5 = elapsed ticks (first value > a0)."""
        x = m.cpu.x
        limit = (x[10] * ticks_per_unit) & 0xFFFFFFFF
        start = m.ticks()
        m.cpu.total += limit // TICKS_PER_STEP + 1
        x[13], x[14], x[15] = start, 0x80140000, (m.ticks() - start) & 0xFFFFFFFF
        return limit

    def _endpoint(self, m):
        x = m.cpu.x
        endpoint, buffer, length = x[10], x[11], x[12]
        self.reports.append((endpoint, m.bus.peek(buffer, length).hex(),
                             round(m.milliseconds(), 3)))
        return 0

    def _flash_read(self, m):
        """Flash read helper 0x2000D510(address, length, destination).

        Only the macro sector is modelled; any other flash read stops."""
        x = m.cpu.x
        address, length, destination = x[10], x[11], x[12]
        base = 0x89000 + m.gp(396, 2)
        if not (base <= address and address + length <= base + 512):
            raise RuntimeError(f'unmodelled flash read {address:#x}+{length}')
        offset = address - base
        m.bus.poke(destination, self.macro_flash[offset:offset + length])
        return 0

    def _matrix(self):
        return 4904 if self.machine.gp(133) else 4856

    def key(self, position, down):
        self.scan([(position, down)])

    def scan(self, changes):
        """Apply several key changes in one matrix scan.

        Like the scan loop at 0x3268..0x328C, dispatch runs once per changed
        column in column order; reports go out afterwards from the main loop.
        """
        m = self.machine
        base = self._matrix()
        columns = set()
        for position, down in changes:
            column, row = position % COLUMNS, position // COLUMNS
            state = m.gp(base + column)
            state = state | (1 << row) if down else state & ~(1 << row)
            m.set_gp(base + column, state)
            columns.add(column)
        for column in sorted(columns):
            m.call(DISPATCH, column)
        self.idle(1)

    def idle(self, passes=1):
        m = self.machine
        for _ in range(passes):
            m.call(SELECT_SENDER)
            if self.macro_flash is not None:
                m.call(MACRO_INTERPRETER)
                m.call(SELECT_SENDER)
            delay = m.gp(394, 2)
            if delay:
                m.set_gp(394, delay - 1, 2)

    def tap(self, *positions):
        for position in positions:
            self.key(position, True)
        for position in reversed(positions):
            self.key(position, False)

    def take(self):
        reports, self.reports = self.reports, []
        return reports
