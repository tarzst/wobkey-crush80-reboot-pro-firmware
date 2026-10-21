# WOBKEY Crush 80 Reboot Pro RGB — macOS/VIA firmware patch

This repository contains reproducible patches for the official WOBLAB Crush 80
RGB firmware dated 2026-06-18 (USB release 0108), for the **Reboot Pro RGB**.
The original RC2 fixes macOS layers. The newer **NativeHeld preview** adds held
QMK modifier combinations and transparent layers, with replacement keymap and
macro handling. It is not a complete QMK firmware port.

NativeHeld was tested on one keyboard: held combinations on macOS over USB,
VIA/macros, Fn layers, BLE typing and persistence after reconnect. It retains
known limitations, including a modeled race in the OEM USB sender. Read
[NativeHeld behavior, validation and limitations](docs/NATIVEHELD.md) before use.

## RC2 behavior

The stock firmware stores four VIA layers but uses only layers 0/1. In macOS
mode it applies hard-coded modifier and F-row translations after reading the
keymap, so custom VIA assignments on layers 2/3 are ignored.

The patched firmware:

- uses layers 0/1 in Windows mode;
- uses layers 2/3 in macOS mode;
- disables the hard-coded macOS key translation;
- retains the official working `DYNAMIC_KEYMAP_SET_BUFFER` (`0x13`) handler;
- leaves boot, USB initialization, OTA, transport and RGB code unchanged.

Hardware testing on a Crush 80 Reboot Pro RGB confirmed successful OTA,
re-enumeration, CRC verification, VIA layout loading, Win/Mac layer switching,
custom F-row bindings and persistent wired RGB settings.

## Firmware files

| File | SHA-256 | OTA CRC |
|---|---|---|
| `firmware/official/Crush80-RGB-20260618-official.bin` | `b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da` | `ca2d85dc` |
| `firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin` | `7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88` | `fe1aa4c2` |
| `firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin` (preview) | `7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35` | `350ad5c5` |

## Reproduce the patch

```bash
python3 src/build_firmware.py \
  firmware/official/Crush80-RGB-20260618-official.bin \
  /tmp/Crush80-RGB-20260618-MacLayers-RC2.bin
sha256sum /tmp/Crush80-RGB-20260618-MacLayers-RC2.bin
```

To compile NativeHeld from its C/assembly sources with the reference RISC-V
GCC toolchain:

```bash
python3 src/build_nativeheld.py --cc /path/to/riscv64-unknown-elf-gcc
```

The builder requires the exact tested output hash; toolchain details and the
fixed placement are documented in [NATIVEHELD.md](docs/NATIVEHELD.md).

Run the public tests with:

```bash
python3 -m unittest discover -s tests -v
```

## Flash over wired USB

Save the VIA layout/macros and RGB settings first; OTA resets settings. Connect the keyboard directly by cable in wired
mode, close VIA and other applications using the HID interfaces, then run:

```bash
python3 tools/crush80.py info
python3 tools/crush80.py flash \
  firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin --yes
```

The flasher accepts the patched image only when the keyboard reports the exact
official/RC2 CRC (`ca2d85dc`/`fe1aa4c2`), or NativeHeld CRC `350ad5c5` for
rollback. It requires an explicit final OTA success reply, opens a fresh HID
connection after restart, and verifies CRC `fe1aa4c2`. NativeHeld installation
and its accepted source versions are documented [separately](docs/NATIVEHELD.md#flasher-policy).

The official Windows updater can restore the official 2026-06-18 firmware as
long as the OTA interface still enumerates.

## Known stock RGB issue

Effect ID 11 (`FLOWERS_OPEN_MODE`) is stored correctly and VIA still reports 11
after a cold start, but the RGB engine visually starts effect 2. All other IDs
0–18 persist correctly. This patch deliberately leaves the RGB startup code
unchanged; avoid effect 11.

See [the Russian technical report](docs/TECHNICAL.ru.md) for offsets, validation
and hardware results.

The [development roadmap (Russian)](docs/VIA-ROADMAP.ru.md) records the scope and
remaining work. `QK_MODS`/`KC_TRNS` support belongs to NativeHeld; RC2 remains
available as the previous release.
