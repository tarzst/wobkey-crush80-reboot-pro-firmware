# NativeHeld — 2026-11-01 (`v1.3.0`)

This document covers the hardware-tested NativeHeld application images for the
WOBKEY Crush 80 Reboot Pro RGB, based on official USB release 0108. They add
full QMK/VIA layer operators (`MO`, `TG`, `TO`, `DF`, `OSL`, `TT`, `LM`,
`FN_MO13`/`FN_MO23` Tri-Layer, multi-layer `KC_TRNS`), Tap-Hold (`MT`/`LT`) with
Quick Tap auto-repeat and bidirectional rolling-safe Permissive Hold, Caps Word
(`Both Shifts` or `0x7C73` `CW_TOGG`), One-Shot Modifiers (`OSM`), Grave Escape
(`KC_GESC`), held `QK_MODS` bindings, dirty-layer flash persistence, and Telink
B91 hardware watchdog protection to RC2. This is an experimental,
hardware-tested firmware patch, not a full QMK port or a guarantee against
bricking.

- Current release (`v1.3.0`, 2026-11-01):
  - File: `firmware/patched/Crush80-RGB-0108-NativeHeld-20261101.bin`
  - Reference ELF: `firmware/nativeheld/NativeHeld-20261101.elf`
  - Size: 124436 bytes (`8044 / 8132` payload bytes used)
  - SHA-256: `3b6c6755b1a3b263d6e55c2a4415d7e91689ac43f897b3be970b236ef970de3a`
  - OTA CRC: `2f4f4974`
- Refactored preview (`preview.2`, 2026-10-31):
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
- Multi-layer `KC_TRNS` searches top-down across active layers (`3 -> 2 -> 1 -> 0`)
  down to the effective base layer (`0` on Windows, `2` on macOS, or `DF` base).
- QMK/VIA layer operators: `MO`, `TG`, `TO`, `DF`, `OSL` (One-Shot Layer),
  `TT` (Tap-Toggle Layer), `LM(layer, mod)` (`0x5000..0x507F`), and
  `FN_MO13` / `FN_MO23` Tri-Layer (`0x7700..0x7701`, `0x5F10..0x5F11`).
- Tap-Hold `MT(mod, kc)` (`0x2000..0x3FFF`) and `LT(layer, kc)` (`0x4000..0x43FF`)
  use a 200 ms tapping term (`3 200 000` ticks of the 16 MHz timer `0x80140200`),
  **Quick Tap** auto-repeat (`Tap -> Hold` within 200 ms holds `kc`),
  `HOLD_ON_OTHER_KEY_PRESS` for `LT`, and bidirectional rolling-safe
  **Permissive Hold** for `MT`.
- **Caps Word** (`Both Shifts` `KC_LSFT + KC_RSFT` or `0x7C73` `CW_TOGG`)
  automatically shifts `A..Z` and `-` (`_`), preserves mode on digits `1..0`,
  `Backspace` and `Delete`, and deactivates on `Space` or other keys.
- One-Shot Modifiers `OSM(mod)` (`0x52A0..0x52BF`) latch modifiers for the next
  non-modifier key on a quick tap (stacking multiple `OSM` taps), or act as a
  held modifier when held across another key or past 200 ms.
- Grave Escape `KC_GESC` (`0x7C16` / `0x5C16`) emits `KC_GRV` (`0x35`) when
  `Shift` or `GUI` is active (including `OSM`), and `KC_ESC` (`0x29`) otherwise.
- `QK_MODS` presses its modifiers and basic usage until the physical key is
  released. Release uses the latched action, including when Fn is released first.
- Independent owners retain shared modifiers/usages until the last owner releases.
- Telink B91 hardware watchdog (`0x8014014C = 0x0B700000` ~4.0 s at 48 MHz PCLK,
  `0x80140142 = 0x80`) is armed and cleared (`0x80140143 = 0x0C`) on every
  main-loop pass once `READY == 8`. Replacing the dead stock layer handler
  `0x12F18..0x130B4` also removes the stock `gp+804 & 0x20` status-bit collision
  between `MO(1)` and background RGB flash persistence (`0x1AC64` -> `0x8A000`).
- The command handler supports VIA keymap, encoder, RGB and 16 macro slots.
  The macro buffer is 512 bytes. The final 28-byte read starting at offset 504
  is accepted, matching the request made by usevia.app.
- Macro uploads preserve byte 511. Playback uses a bounded 32-byte streaming
  cache; physical, builtin and macro keyboard actions share ownership state.

Examples used in the tested Mac layout: `0x0A22` (Shift+GUI+5), `0x0914`
(Ctrl+GUI+Q), `0x0814` (GUI+Q), `0x0152` (Ctrl+Up), `0x082C` (GUI+Space), as
well as `MT`, `LT`, `OSL` and `OSM` bindings.

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
  firmware/patched/Crush80-RGB-0108-NativeHeld-20261101.bin --yes
```

Flashing is optional and carries the limitations above. This repository update
does not perform an update on any connected device.
