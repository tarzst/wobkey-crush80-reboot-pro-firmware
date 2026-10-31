# NativeHeld preview — 2026-10-31 (`v1.1.0-nativeheld-preview.2`)

This document covers the hardware-tested NativeHeld application images for the
WOBKEY Crush 80 Reboot Pro RGB, based on official USB release 0108. They add
held `QK_MODS` bindings and transparent extra layers to RC2. This is an
experimental, hardware-tested preview, not a full QMK implementation or a
guarantee against bricking.

- Current image (`preview.2`, 2026-10-31):
  - File: `firmware/patched/Crush80-RGB-0108-NativeHeld-20261031.bin`
  - Reference ELF: `firmware/nativeheld/NativeHeld-20261031.elf`
  - Size: 124436 bytes (`7563 / 7716` payload bytes used)
  - SHA-256: `46c51d50748dcef47c0e1bf2b0460bf2441e626ed8f4cf73eec2498ce6c363d0`
  - OTA CRC: `239d8875`
- Initial preview (`preview.1`, 2026-10-21):
  - File: `firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin`
  - Reference ELF: `firmware/nativeheld/NativeHeld-20261021.elf`
  - Size: 124436 bytes (`7613 / 7716` payload bytes used)
  - SHA-256: `7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35`
  - OTA CRC: `350ad5c5`

## Behavior

- Windows uses layers 0/1, macOS uses 2/3, as in RC2.
- `KC_TRNS` on layer 1 or 3 falls back to its paired base, 0 or 2.
- `QK_MODS` presses its modifiers and basic usage until the physical key is
  released. Release uses the latched action, including when Fn is released first.
- Independent owners retain shared modifiers/usages until the last owner releases.
- The command handler supports VIA keymap, encoder, RGB and 16 macro slots.
  The macro buffer is 512 bytes. The final 28-byte read starting at offset 504
  is accepted, matching the request made by usevia.app.
- Macro uploads preserve byte 511. Playback uses a bounded streaming cache;
  physical, builtin and macro keyboard actions share ownership state.

Examples used in the tested Mac layout: `0x0A22` (Shift+GUI+5), `0x0914`
(Ctrl+GUI+Q), `0x0814` (GUI+Q), `0x0152` (Ctrl+Up), `0x082C` (GUI+Space).
This does not add MT/LT, One-Shot or arbitrary mixed left/right modifiers.

## Reproduce from C and assembly

Python 3 and an RV32-capable `riscv64-unknown-elf-gcc` toolchain are required.
The reference build used GCC 14.2.0 and binutils
2.45.50.20251209-1ubuntu1+7build1 on Linux ARM64; package identities and hashes
are recorded in `src/nativeheld/toolchain.json`. Compiler versions can change
code generation. The builder rejects any section or final SHA that differs
from the tested image.

```bash
# Verify the published hardware-tested release (350ad5c5) from its reference ELF:
python3 src/build_nativeheld.py --verify

# Build the current refactored source tree against src/nativeheld/plan.json:
python3 src/build_nativeheld.py --cc /path/to/riscv64-unknown-elf-gcc

# Re-pack sections and refresh layout.ld / plan.json after C/ASM changes:
python3 src/build_nativeheld.py --cc /path/to/riscv64-unknown-elf-gcc --repack
```

The builder derives the pinned transparent-layer base from RC2, compiles the
published modules into the fixed placement in `src/nativeheld/layout.ld`, and
applies the 18 entry/reset hooks. It checks every compiled section against
`plan.json`, audits `gp` register usage and symbol resolution, preserves
application startup and initializer sources, and requires the original image
length and tested CRC/SHA. It never opens a keyboard.

`firmware/nativeheld/NativeHeld-20261021.elf` contains the reference placed
payload for the hardware-tested `2026-10-21` release (`350ad5c5`). Subsequent
source refactoring in `src/nativeheld/` (shared `core/oem_b91.h` memory map,
dirty-layer tracking in `via_commands.c:keymap_write` to avoid redundant flash
writes, and `valid_writer` inlining) reduces the placed payload from
`7613 / 7716` to `7563 / 7716` bytes while keeping the published release image
and flasher allowlist intact.
The original vendor firmware remains proprietary; this is a binary patch with
source for the replacement components, not the manufacturer's firmware source.

## Validation

On the tested keyboard, the user confirmed native held combinations on Mac
over USB and BLE, working Fn layers, cold startup, sleep/wake, and macro
availability/playback in VIA.
Read-back after reconnect confirmed the native layout, macro buffer and RGB
settings persisted. RGB effect 5 matched after USB → BLE → USB.

The development and public checks (`tests/rc2emu/`, `tests/test_nativeheld.py`,
`tests/nativeheld_check.c`) execute actual RV32IMC/XAndes instructions across
cold start (`PC = 0` to `MAIN_LOOP`), source ownership/release ordering, VIA
keymap/macro commands, dirty-layer flash persistence, macro streaming with
re-entrancy guards, atomic reset scopes, ELF `gp` auditing, and malformed ELF
rejection. These models stub flash, time, endpoints or radio operations as
appropriate. They do not prove hardware timing, every computed callback or all
nested interrupt paths.

Not confirmed on hardware: native combinations over 2.4 GHz, every
overflow/reconnect/sleep case, and the byte-511 fix using a fresh `0xFF` tail.
The latter is covered offline; the hardware backup already contained `0x00`.

## Known limitations

- The retained OEM USB sender has a modeled race: an interrupt between FIFO
  byte copies and the caller's dirty-flag acknowledgement can lose a release
  update. It was reproduced in instruction emulation; the user has not reported
  it on hardware. This image does not fix that race. A successful normal-use
  test does not establish that all interrupt interleavings are safe.
- Stock RGB effect 11 remains inconsistent after startup/transport changes.
  Avoid it; this release does not change the RGB startup implementation.
- OTA resets settings. Export the VIA layout/macros and record RGB settings
  before an update, then restore them and check after reconnecting.
- Recovery with the official Windows updater requires a working OTA interface.
  Preserving startup/OTA bytes does not guarantee software recovery if the
  application stops enumerating.

## Flasher policy

The public flasher accepts this exact target hash from official 0108, RC2,
the checked TRNS base, the earlier NativeHeld preview, or the same NativeHeld
image. These source CRCs are explicitly listed in `tools/crush80.py`.
The hardware update recorded here was the earlier NativeHeld preview
(`dca8651c`) → this image (`350ad5c5`); every accepted transition has not been
separately exercised on hardware. Official/RC2 targets also accept `350ad5c5`
for rollback. No generic override or image-length extension was added.

After saving settings, a deliberate update uses:

```bash
python3 tools/crush80.py info
python3 tools/crush80.py flash \
  firmware/patched/Crush80-RGB-0108-NativeHeld-20261031.bin --yes
```

Flashing is optional and carries the limitations above. This repository update
does not perform an update on any connected device.
