# Binary patch map

Base: `firmware/official/Crush80-RGB-20260618-official.bin`

| Offset | Original | Patched | Purpose |
|---:|---|---|---|
| `0x10A8` | 28 zero bytes | layer selection routine | Map macOS 0/1 to 2/3 |
| `0x12C5C` | `03c6a801` | `13060000` | Disable hidden modifier translation |
| `0x13230` | `8b658017` | `6fd09ee7` | Jump to layer selection routine |
| `0x13258` | `834fab01` | `930f0000` | Disable hidden direct-key translation |
| `0x13338` | `8342ab01` | `93020000` | Disable hidden active-layer translation |
| `0x134F8` | `8342ab01` | `93020000` | Disable hidden alternate-layer translation |

The final four image bytes are regenerated OTA CRC32. No RGB code is patched.
