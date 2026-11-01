# WOBKEY Crush 80 Reboot Pro RGB — macOS/VIA firmware patches

[Русский](README.ru.md)

Reproducible patches for the **WOBKEY Crush 80 Reboot Pro RGB**, based on
official WOBLAB firmware dated 2026-06-18 (USB release **0108**).

The current release is [**NativeHeld — v1.2.0**](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.2.0).
It adds full QMK/VIA layer operators (`MO`, `TG`, `TO`, `DF`, `OSL`, `TT`,
`FN_MO13`/`FN_MO23` Tri-Layer, multi-layer `KC_TRNS`), Tap-Hold (`MT(mod, kc)`
and `LT(layer, kc)`), One-Shot Modifiers (`OSM`), Layer-Mod (`LM`), Grave
Escape (`KC_GESC`), native held `QK_MODS` combinations, dirty-layer flash
persistence, and Telink B91 hardware watchdog protection (~4.0 s timeout) on top
of the macOS layer fixes.

**Experimental, hardware-tested on one keyboard. This is not a full QMK port.**
Read the [validation scope and known limitations](docs/NATIVEHELD.md) before use.

## What NativeHeld changes

The stock firmware applies hard-coded modifier and F-row translations in
macOS mode, overriding custom VIA assignments. The patches make VIA bindings
control the resulting keys:

- Windows uses layers **0/1**; macOS uses **2/3**, including custom F-row bindings.
- Multi-layer `KC_TRNS` searches from the highest active layer (`3 -> 2 -> 1 -> 0`)
  down to the active OS base (`0` on Windows, `2` on macOS, or custom `DF` base).
- Full QMK/VIA layer operators: `MO`, `TG`, `TO`, `DF`, `OSL` (One-Shot Layer),
  `TT` (Tap-Toggle Layer), `LM(layer, mod)` and `FN_MO13` / `FN_MO23` Tri-Layer.
- Tap-Hold keys `MT(mod, kc)` (`0x2000..0x3FFF`) and `LT(layer, kc)` (`0x4000..0x43FF`)
  with a 200 ms tapping term and `HOLD_ON_OTHER_KEY_PRESS`.
- One-Shot Modifiers `OSM(mod)` (`0x52A0..0x52BF`) with multi-modifier stacking
  and hold fallback, plus Grave Escape `KC_GESC` (`0x7C16`: `Esc` normally,
  `~` / `` ` `` with `Shift` / `GUI`).
- Native `QK_MODS` combinations hold modifiers and the basic key until physical
  release. Releasing Fn first still releases the action selected on key-down.
- Shared modifiers and key usages remain held until their last owner releases.
- Hardware watchdog (`0x8014014C = 0x0B700000` ~4.0 s, `0x80140142 = 0x80`) is
  enabled and serviced on each main-loop pass, and the stock `gp+804 & 0x20`
  status-bit collision between `MO(1)` and RGB flash persistence is eliminated.
- VIA keymap, encoder, RGB and 16 macro slots are supported. The replacement
  handler fixes the final macro-buffer read used by usevia.app and preserves
  macro byte 511.

Examples from the tested Mac layout include Shift+GUI+5, Ctrl+GUI+Q, GUI+Q,
Ctrl+Up and GUI+Space, as well as `MT`, `LT`, `OSL` and `OSM` bindings.

## Choose a release

| Release | Scope |
|---|---|
| [NativeHeld v1.2.0](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.2.0) | Current release: macOS layers, full QMK/VIA layer stack (`MO`/`TG`/`TO`/`DF`/`OSL`/`TT`/`LM`/Tri-Layer/`KC_TRNS`), `MT`/`LT` Tap-Hold, `OSM`, `KC_GESC`, held `QK_MODS`, dirty-layer flash persistence, and hardware watchdog. |
| [NativeHeld preview](https://github.com/tarzst/wobkey-crush80-reboot-pro-firmware/releases/tag/v1.1.0-nativeheld-preview.2) | Earlier preview: macOS layers, transparent Fn-layer keys, held `QK_MODS` and replacement VIA/macro handling. |
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
   git clone --branch v1.2.0 --depth 1 \
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
     firmware/patched/Crush80-RGB-0108-NativeHeld-20261101.bin --yes
   ```

The flasher checks the exact image hash and permitted source CRC, waits for
OTA success, then verifies CRC **13dadb12** on a fresh connection. It refuses
unknown target images and unlisted source versions. See the
[transition policy and hardware-testing limits](docs/NATIVEHELD.md#flasher-policy).
Restore your settings after the update and check your bindings after reconnecting.

For an offline packet check that does not open the keyboard:

```bash
python3 tools/crush80.py dry-run \
  firmware/patched/Crush80-RGB-0108-NativeHeld-20261031.bin
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
| [NativeHeld preview.2 (2026-10-31)](firmware/patched/Crush80-RGB-0108-NativeHeld-20261031.bin) | `46c51d50748dcef47c0e1bf2b0460bf2441e626ed8f4cf73eec2498ce6c363d0` | `239d8875` |
| [NativeHeld preview.1 (2026-10-21)](firmware/patched/Crush80-RGB-0108-NativeHeld-20261021.bin) | `7d154c51564138a5e2307d5da40b66a432452628b826592a73795d078ed49e35` | `350ad5c5` |
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
