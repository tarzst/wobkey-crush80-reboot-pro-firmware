# Crush 80 firmware project context

## Current result — 2026-10-21

NativeHeld preview is hardware-tested on one Crush 80 Reboot Pro RGB. The exact
image SHA-256 is `7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35`,
OTA CRC `350ad5c5`, size 124436 bytes. The owner confirmed native held chords
on macOS over USB, VIA commands/macros, Fn layers, BLE typing and persistence
of the native layout after reconnect. This is a functional milestone, not
proof that every transport, interrupt and power-management case is safe.

## Milestones

1. Official WOBLAB RGB 2026-06-18 / USB release 0108: source image in
   `firmware/official/`, SHA `b1dcb56d…686da`, CRC `ca2d85dc`.
2. RC2: Windows layers 0/1, Mac layers 2/3, removal of hard-coded Mac remapping;
   retains OEM VIA buffer handling. SHA `7663f2fc…e7d88`, CRC `fe1aa4c2`.
3. Transparent-layer base: `KC_TRNS` on layer 1/3 falls back to 0/2. Reproduced
   from RC2 by `src/nativeheld/trns.py`, SHA `31722203…918b`, CRC `54ab7ac3`.
4. NativeHeld: per-position press-time latches and independent physical,
   builtin and macro owners; shared report contributions, streaming macros,
   replacement VIA commands and short interrupt guards.
5. The first NativeHeld preview exposed two VIA compatibility bugs. The app
   reads 28 bytes at macro offset 504, so rejecting a read crossing byte 512
   makes VIA report macros unsupported. Macro commit must preserve byte 511.
   The published `7d154c51…` image includes both corrections.
6. The owner authorized that exact image, flashed it, restored settings, then
   replaced five macro bindings with native `QK_MODS` and confirmed they work.
7. Public packaging preserves those exact bytes, publishes replacement C/
   assembly sources and a fixed linker placement, and reproduces the same SHA.

## Files and architecture

- `src/build_firmware.py`: original RC2 patch builder.
- `src/build_nativeheld.py`: compile and assemble the pinned NativeHeld image.
- `src/nativeheld/compact/`: ownership, delta adapter, streaming macros, VIA
  commands and firmware binding; `firmware_hooks.S` preserves the OEM ABI.
- `src/nativeheld/core/`: shared interface headers, interrupt guard and memory
  helpers used by those modules; not a separate full firmware implementation.
- `src/nativeheld/layout.ld` and `plan.json`: verified fixed placement,
  section hashes, absolute ROM symbols and all 18 entry/reset hooks.
- `src/nativeheld/toolchain.json`: reference GCC/binutils package identities.
- `firmware/nativeheld/`: reference payload ELF and release manifest.
- `tools/crush80.py`: exact-hash OTA policy, source CRC gates and fresh-connection
  verification. Packaging/build/tests must never call its device commands.
- `tests/`: public artifact, policy and host-C behavior tests.
- `docs/NATIVEHELD.md`: validation scope, reproduction and known limitations.
- `docs/VIA-ROADMAP.ru.md`: original requirements and remaining scope.

The replacement occupies 7613 of 7716 selected bytes. Persistent ownership
state is 420 bytes; engine metadata 28 and playback cache 64 reuse the original
512-byte macro playback object at `0x80BE4`. A runtime reset preserves the
in-flight binding lease; cold initialization clears it. Journal scratch data
uses live stack storage. No permanent stack reservation or image extension is
introduced. Firmware startup and initializer source ranges remain unchanged.

## Known issues and limits

- The retained OEM USB sender has a confirmed instruction-model race. An IRQ
  during FIFO copying and dirty-flag acknowledgement can lose a release update.
  NativeHeld does not fix it. It has not been reported by the owner on hardware.
- Stock RGB effect 11 remains inconsistent. Effect 5 was checked across
  USB → BLE → USB; separate per-transport RGB profiles were not established.
- Native chords over BLE/2.4 GHz and all sleep/overflow/nested-IRQ cases are not
  hardware-verified. Cold-start/sleep modeling is not hardware equivalence.
- The macro byte-511 fix is verified offline. Hardware backup/read-back already
  contained zero there, so it did not independently validate a fresh `0xFF` tail.
- MT/LT, One-Shot and full QMK behavior are outside this preview.
- OTA clears settings and recovery requires the OTA interface to enumerate.

## Maintenance rules

Keep RC2 and the tested NativeHeld image intact. A firmware source change is a
new candidate, requires fresh placement/ABI/behavior checks, and cannot inherit
the previous image's hardware approval. Do not change boot/OTA or broaden the
image-size policy as a shortcut. Distinguish model evidence from hardware
observations. Record subsequent milestones and exact image hashes here.
