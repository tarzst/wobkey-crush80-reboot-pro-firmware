# Crush 80 firmware project context

## Current result — 2026-11-01 (`v1.3.0`)

NativeHeld `v1.3.0` is flashed on the owner's Crush 80 Reboot Pro RGB.
The exact image (`firmware/patched/Crush80-RGB-0108-NativeHeld-20261101.bin`)
has SHA-256 `3b6c6755b1a3b263d6e55c2a4415d7e91689ac43f897b3be970b236ef970de3a`,
OTA CRC `2f4f4974`, reference ELF `firmware/nativeheld/NativeHeld-20261101.elf`
SHA-256 `061883a5f06d25e8915162745f3f47289a44461445a3d1d17dc0ebe9dabdfe9f`,
size 124436 bytes (`8044 / 8132` payload bytes across 17 regions, 41 sections).
It implements full QMK/VIA layer operators (`MO`, `TG`, `TO`, `DF`, `OSL`, `TT`,
`LM`, `FN_MO13`/`FN_MO23` Tri-Layer, multi-layer `KC_TRNS`), Tap-Hold (`MT`/`LT`)
with **Quick Tap** auto-repeat and bidirectional rolling-safe **Permissive Hold**,
**Caps Word** (`Both Shifts` or `0x7C73` `CW_TOGG`), One-Shot Modifiers (`OSM`),
`KC_GESC`, held `QK_MODS` chords, dirty-layer flash persistence, and Telink B91
hardware watchdog protection (`0x8014014C = 0x0B700000` ~4.0 s, `0x80140142 = 0x80`,
cleared via `0x80140143 = 0x0C` on each main-loop pass), while eliminating the
stock `0x12F18` `gp+804 & 0x20` status-bit collision with background RGB flash
saves. Earlier `preview.1` (`7d154c51…`, `350ad5c5`) and `preview.2`
(`46c51d50…`, `239d8875`) remain in the repository and flasher allowlist
(alongside `13dadb12` as an accepted source CRC). This is a functional milestone,
not proof that every transport, interrupt and power-management case is safe.

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
8. GitHub prerelease `v1.1.0-nativeheld-preview.1` was published at commit
   `42cae6a`, with the exact BIN, reference ELF, manifest and asset checksums.
   English and Russian READMEs now lead with that preview, link both releases
   and use NativeHeld in the main installation example.
9. After publication, the owner reported that the proposed BLE checks passed,
   including native chords, cold startup and sleep. This is a user-reported
   manual result, not a captured exhaustive test matrix; 2.4 GHz is not covered.

## Review — 2026-10-22

See [review findings](docs/REVIEW-20261022.ru.md). An unchanged keymap upload
was reproduced making 40 Flash program calls (10240 bytes). A cache32 payload
experiment freed 32 bytes of workspace and reduced allocated code/data by
6 bytes; it linked in the existing regions and passed limited public host-C
scenarios, but is not a flashable/released candidate. Production sources and
images remain unchanged. Public tests passed (10/10), and the original full
build reproduced the published SHA. Power-loss journal rollover and public
integration-test gaps remain review findings.

## Intermittent runtime freeze report — 2026-10-31

The owner clarified: switching lighting effects by keyboard bindings (keys,
logo, side) sometimes freezes all animation and input, requiring power off.
It occurs on USB/BLE/2.4 GHz regardless of switching speed. Connection-mode
switches work; the earlier transport-switch interpretation is withdrawn.
The owner subsequently confirmed freezes also occur without effect switching;
RGB is therefore not a necessary trigger. Idle versus typing was not separated.
No captured hardware reproduction or stock/RC2 comparison yet. A dispatch-only
instruction model completed58 effect/release-order scenarios on each of stock
and NativeHeld, but does not cover renderer/main-loop/async IRQ behavior.
See [diagnostic issue](docs/ISSUE-RUNTIME-FREEZE.ru.md). Firmware remains unchanged.

First live USB trial confirmed CRC350ad5c5 / release0108. The owner completed
effect cycles for all three lighting zones without freezing. All296 main-RGB
GET samples over295 seconds succeeded; logo/side effects were observed by the
owner, not read by this command. Input capture and a read-only keymap snapshot
were saved in the research project's rgb-freeze-20261031 directory. The second
input-only trial without GET polling also passed two cycles per lighting zone
according to the owner;108 HID reports and108 EV_KEY events were captured.
Both captures are stopped. No freeze reproduced; post-trial VIA/info responded,
CRC unchanged. No firmware or settings writes were performed by the tools.
Broaden investigation to general runtime IRQ/stack/peripheral waits, including
OEM paths; an ISR/MIE fault is a hypothesis, not a measured result.

A subsequent static and `rc2emu` runtime audit (recorded in
`docs/ISSUE-RUNTIME-FREEZE.ru.md`) mapped all PLIC vectors (`mtvec = 0x8A00`),
CSR transitions, WS2812 DMA (`0xCB30` / IRQ 23 `0x257C`), MSPI flash wrappers,
and all 500 RGB mode combinations (`0xA104` / `0xCD88`). It identified that
stock `main` (`0x40BC`) sets `0x80140142 = 0x20` without bit 7 (`0x80`,
`FLD_TMR_WD_EN`), leaving the CPU exception trap `vec[0]` (`0x2D6C`) as an
unrecovered infinite loop with `MIE = 0` despite periodic `0x80140143 = 0x0C`
watchdog clears. It also documented the two matrix scan paths selected by
`gp+133` (`Fn+H` `0x5F8D`), where `gp+133 != 0` invokes `0x130B8 -> 0x13268`
directly inside `timer0_irq_handler` (`0x2B80`).

## Refactoring and build consolidation — 2026-10-31

- `src/nativeheld/core/`: removed 4 unused legacy headers (`physical_binding.h`,
  `stock_adapter.h`, `stock_reports.h`, `synthetic_binding.h`), trimmed unused
  legacy declarations from `via_core.h`, and consolidated all Telink B91 OEM
  GP offsets, MMIO addresses and flash layout constants into `core/oem_b91.h`.
- `src/nativeheld/compact/via_commands.c`: `keymap_write` now tracks a bitmask
  of modified 256-byte layers (`dirty`) under `vci_enter/leave` and calls
  `persist(layer)` only for changed layers, eliminating 40 redundant flash
  writes and 4 sector erases on unchanged VIA layout uploads (`REVIEW-20261022` P2).
- `src/nativeheld/compact/delta_adapter.c`: marked `valid_writer` as
  `__attribute__((always_inline)) static inline`, allowing LTO constant folding.
- `src/build_nativeheld.py` and `src/nativeheld/elf_layout.py`: integrated
  deterministic section packing (`--repack`), two-pass linker relaxation
  measurement, ELF symbol verification and `gp` instruction auditing.
  `--verify` reconstructs the published `2026-10-21` release (`350ad5c5`) from
  `firmware/nativeheld/NativeHeld-20261021.elf`, while the refactored source
  tree packs into `7563 / 7716` bytes (41 sections, 153 bytes free) and builds
  `firmware/patched/Crush80-RGB-0108-NativeHeld-20261031.bin` (SHA-256
  `46c51d50748dcef47c0e1bf2b0460bf2441e626ed8f4cf73eec2498ce6c363d0`, OTA CRC
  `239d8875`, ELF `firmware/nativeheld/NativeHeld-20261031.elf` SHA-256
  `22a7d5b3deb0c75b51ab08ab596f07b9dd6a6cd8c94cf11b605f0f9a231b2544`).
- Hardware verification (2026-10-31): the owner approved and flashed
  `Crush80-RGB-0108-NativeHeld-20261031.bin` via `tools/crush80.py`; the device
  rebooted and confirmed `CRC=239d8875` (`release=0108`). The 1024-byte keymap
  and a clean 512-byte macro slot (two-phase transaction `511:0xFF` -> data ->
  `511:0x00`) were restored and verified on hardware by the owner.
- `tests/rc2emu/` and `tests/test_nativeheld.py`: bundled standalone RV32IMC +
  XAndes emulator (`rc2emu`) and expanded public tests to 14 suites covering
  cold start (`Live`), native chords, macro flash streaming with `binding_active`
  guards, atomic reset scopes, and VIA `0x13` dirty-layer flash persistence.

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

The replacement occupies 8004 of 8132 selected bytes across 17 code regions
(including the retired stock layer handler `0x12F18..0x130B4` merged into
Region 4 `0x12C28..0x130B4`). Persistent ownership state is 420 bytes, layer
and Tap-Hold/OSM state is 32 bytes, engine metadata is 28 bytes and macro
playback cache is 32 bytes, reusing the original 512-byte macro playback object
at `0x80BE4..0x80DE4` while keeping the 512-byte VIA macro staging buffer at
`0x80DE4..0x80FE4` intact. A runtime reset preserves the in-flight binding
lease, toggled layers (`TG`) and custom default layer (`DF`); cold
initialization clears all 512 bytes. Journal scratch data uses the macro
streaming cache or live stack storage. No permanent stack reservation or image
extension is introduced. Firmware startup and initializer source ranges remain
unchanged.

## Known issues and limits

- The retained OEM USB sender has a confirmed instruction-model race. An IRQ
  during FIFO copying and dirty-flag acknowledgement can lose a release update.
  NativeHeld does not fix it. It has not been reported by the owner on hardware.
- Stock RGB effect 11 remains inconsistent. Effect 5 was checked across
  USB → BLE → USB; separate per-transport RGB profiles were not established.
- Native chords over BLE, cold startup and sleep passed the owner's manual
  checks. Native chords over 2.4 GHz and exhaustive sleep/overflow/nested-IRQ
  cases remain unverified. Modeling is not hardware equivalence.
- The macro byte-511 fix is verified offline. Hardware backup/read-back already
  contained zero there, so it did not independently validate a fresh `0xFF` tail.
- OTA clears settings and recovery requires the OTA interface to enumerate.

## Maintenance rules

This session is scoped to Crush 80 only, per owner instruction on 2026-10-24.
Keep unrelated keyboard research outside this project and its session context.

Keep RC2 and the tested NativeHeld image intact. A firmware source change is a
new candidate, requires fresh placement/ABI/behavior checks, and cannot inherit
the previous image's hardware approval. Do not change boot/OTA or broaden the
image-size policy as a shortcut. Distinguish model evidence from hardware
observations. Record subsequent milestones and exact image hashes here.
