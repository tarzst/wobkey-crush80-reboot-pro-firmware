# WOBKEY Crush 80 Reboot Pro RGB — macOS/VIA firmware patches

[Русский](README.ru.md)

Reproducible patches for the **WOBKEY Crush 80 Reboot Pro RGB**, based on
official WOBLAB firmware dated 2026-06-18 (USB release **0108**).

The current release is [**NativeHeld preview — v1.1.0-nativeheld-preview.1**](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.1.0-nativeheld-preview.1).
It adds native held modifier combinations and transparent Fn-layer keys to the
macOS layer fixes, with replacement VIA command and macro handling.

**Experimental, hardware-tested on one keyboard. This is not a full QMK port.**
Read the [validation scope and known limitations](docs/NATIVEHELD.md) before use.

## What NativeHeld changes

The stock firmware applies hard-coded modifier and F-row translations in
macOS mode, overriding custom VIA assignments. The patches make VIA bindings
control the resulting keys:

- Windows uses layers **0/1**; macOS uses **2/3**, including custom F-row bindings.
- `KC_TRNS` on Fn layer 1 or 3 inherits the binding from base layer 0 or 2.
- Native `QK_MODS` combinations hold modifiers and the basic key until physical
  release. Releasing Fn first still releases the action selected on key-down.
- Shared modifiers and key usages remain held until their last owner releases.
- VIA keymap, encoder, RGB and 16 macro slots are supported. The replacement
  handler fixes the final macro-buffer read used by usevia.app and preserves
  macro byte 511.

Examples from the tested Mac layout include Shift+GUI+5, Ctrl+GUI+Q, GUI+Q,
Ctrl+Up and GUI+Space. MT/LT, One-Shot and arbitrary mixed left/right modifier
combinations are not implemented.

## Choose a release

| Release | Scope |
|---|---|
| [NativeHeld preview](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.1.0-nativeheld-preview.1) | Current preview: macOS layers, transparent Fn-layer keys, held modifier combinations and replacement VIA/macro handling. |
| [RC2](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.0.0-rc2) | Earlier macOS layer/F-row fix. Retains the OEM VIA handler; does not add native `QK_MODS` or `KC_TRNS`. |

The NativeHeld release includes the flashable `.bin`, reference payload `.elf`,
`manifest.json` and `SHA256SUMS`. **The ELF is for inspection, not flashing.**
GitHub's source archives include the patch sources, build tools, tests and docs.
The original vendor firmware remains proprietary; these are sources for the
patch and replacement components, not the manufacturer's full firmware source.

## Install NativeHeld over wired USB

1. Export the VIA layout and macros, and record RGB settings. **OTA resets settings.**
2. Download and extract the source archive from the NativeHeld release, or clone
   its tag:

   ```bash
   git clone --branch v1.1.0-nativeheld-preview.1 --depth 1 \
     https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware.git
   cd wobkey-crush80-reboot-pro-firmware
   ```

3. Install Python 3 and the system HIDAPI library. On macOS: `brew install hidapi`.
   The flasher uses HIDAPI directly; no Python packages are required. On Linux,
   your user also needs permission to access the keyboard's HID device.
4. Connect the keyboard by cable in wired mode and close VIA and other apps
   using its HID interfaces. From the extracted/cloned repository, run:

   ```bash
   python3 tools/crush80.py info
   python3 tools/crush80.py flash \
     firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin --yes
   ```

The flasher checks the exact image hash and permitted source CRC, waits for
OTA success, then verifies CRC **350ad5c5** on a fresh connection. It refuses
unknown target images and unlisted source versions. See the
[transition policy and hardware-testing limits](docs/NATIVEHELD.md#flasher-policy).
Restore your settings after the update and check your bindings after reconnecting.

For an offline packet check that does not open the keyboard:

```bash
python3 tools/crush80.py dry-run \
  firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin
```

Official 0108 and RC2 rollback targets are included in the flasher policy.
Software rollback requires a working OTA interface; recovery is not guaranteed
if the application stops enumerating.

## Validation and known limitations

Confirmed on one keyboard: native held combinations on **macOS over USB**, Fn
layers, VIA macro access/playback, BLE typing and persistence of the native
layout, macros and RGB settings after reconnect. RGB effect 5 matched across
USB → BLE → USB. Native combinations over BLE/2.4 GHz have not been
hardware-verified.

- The retained OEM USB sender has a race reproduced in instruction emulation:
  an interrupt during FIFO copying and dirty-flag acknowledgement can lose a
  release update. This preview does not fix it; the owner has not reported it
  on hardware.
- Not every sleep, overflow or nested-interrupt case is hardware-verified.
- Macro byte 511 is fixed and checked offline. The hardware backup already
  contained zero there, so hardware read-back did not independently verify it.
- Stock RGB effect **11** can visually start as effect **2** while VIA still
  reports 11. The patch does not change RGB startup behavior.

Full details: [NativeHeld behavior, build and validation](docs/NATIVEHELD.md).

## Firmware identity

| Image | SHA-256 | OTA CRC |
|---|---|---|
| [NativeHeld preview](firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin) | `7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35` | `350ad5c5` |
| [RC2](firmware/patched/Crush80-RGB-20260618-MacLayers-RC2.bin) | `7663f2fc7357ce3f4ae7f1331577c8e0f2a1bd0f7b1c038a89a6efab31ce7d88` | `fe1aa4c2` |
| [Official 0108](firmware/official/Crush80-RGB-20260618-official.bin) | `b1dcb56d42c0a2fad1006d572392630a5d4c15f92b63f1701784f732426886da` | `ca2d85dc` |

## Reproduce and test

Compile NativeHeld from its C/assembly sources with the reference RISC-V GCC
toolchain:

```bash
python3 src/build_nativeheld.py --cc /path/to/riscv64-unknown-elf-gcc
```

The builder requires the exact tested section hashes and final image hash.
Toolchain details and fixed placement are documented in
[NATIVEHELD.md](docs/NATIVEHELD.md#reproduce-from-c-and-assembly).

Reproduce the earlier RC2 patch:

```bash
python3 src/build_firmware.py \
  firmware/official/Crush80-RGB-20260618-official.bin \
  /tmp/Crush80-RGB-20260618-MacLayers-RC2.bin
```

Run the public artifact and host-C tests:

```bash
python3 -m unittest discover -s tests -v
```

See the [RC2 technical report (Russian)](docs/TECHNICAL.ru.md),
[development roadmap (Russian)](docs/VIA-ROADMAP.ru.md) and
[project context](CONTEXT.md) for implementation details and milestones.
