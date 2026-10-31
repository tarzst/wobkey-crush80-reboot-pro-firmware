/* VIA raw-HID command dispatcher. OEM transport polling and response
 * remain outside this module. No persistent allocation or direct device I/O.
 */
#include "firmware_binding.h"
#include "../core/oem_b91.h"

#define GP               OEM_GP_ADDR
#define CONFIG           OEM_GP_BYTE(OEM_CONFIG_OFFSET)
#define KEYMAP           OEM_BYTE_AT(GP - (uintptr_t)OEM_KEYMAP_NEG_OFFSET)
#define SLOT(layer)      OEM_GP_HALF((uintptr_t)OEM_LAYER_SLOT_OFFSET + 2u * (layer))
#define BYTE(offset)     (*OEM_GP_BYTE(offset))
#define MACRO_SLOT       (*OEM_GP_HALF(OEM_MACRO_SLOT_OFFSET))

static unsigned be16(const uint8_t *p)
{
    return (unsigned)p[0] * 256u + p[1];
}

static void copy(volatile uint8_t *destination, const volatile uint8_t *source, unsigned size)
{
    for (unsigned i = 0; i < size; ++i) {
        destination[i] = source[i];
    }
}

static void persist(unsigned layer)
{
    uint16_t slot = (uint16_t)(*SLOT(layer) + (unsigned)OEM_KEYMAP_LAYER_BYTES);
    uint32_t bank = (uint32_t)OEM_KEYMAP_FLASH_BASE + layer * (uint32_t)OEM_FLASH_SECTOR_BYTES;
    if (slot > 0xe00u || (slot & 255u) != 0) {
        cdb_flash_erase(bank);
        slot = 0;
    }
    cdb_flash_program(bank + slot, (uint32_t)OEM_KEYMAP_LAYER_BYTES,
                      (const uint8_t *)(uintptr_t)(GP - (uintptr_t)OEM_KEYMAP_NEG_OFFSET + layer * (uintptr_t)OEM_KEYMAP_LAYER_BYTES));
    *SLOT(layer) = slot;
}

static void keymap_write(unsigned offset, const uint8_t *data, unsigned size)
{
    unsigned dirty = 0;
    uint32_t saved = vci_enter();
    for (unsigned i = 0; i < size; ++i) {
        unsigned index = offset + i;
        if (KEYMAP[index] != data[i]) {
            KEYMAP[index] = data[i];
            dirty |= 1u << (index / OEM_KEYMAP_LAYER_BYTES);
        }
    }
    vci_leave(saved);
    for (unsigned layer = 0; dirty != 0; ++layer, dirty >>= 1) {
        if ((dirty & 1u) != 0) {
            persist(layer);
        }
    }
}

static void keymap_read(unsigned offset, uint8_t *data, unsigned size)
{
    while (size != 0) {
        unsigned layer = offset / OEM_KEYMAP_LAYER_BYTES, in_layer = offset % OEM_KEYMAP_LAYER_BYTES;
        unsigned take = OEM_KEYMAP_LAYER_BYTES - in_layer;
        if (take > size) {
            take = size;
        }
        cdb_flash_read(OEM_KEYMAP_FLASH_BASE + layer * OEM_FLASH_SECTOR_BYTES + *SLOT(layer) + in_layer,
                       take, data);
        offset += take;
        data += take;
        size -= take;
    }
}

static void rgb(uint8_t *packet, uint8_t write)
{
    unsigned value, base;
    uint8_t legacy = (uint8_t)(CONFIG[31] == 9);
    if (legacy) {
        if (packet[1] < 0x80 || packet[1] > 0x83) {
            return;
        }
        value = (unsigned)packet[1] - 0x80u;
        base = 2;
    } else {
        if (packet[1] != 3 || packet[2] < 1 || packet[2] > 4) {
            return;
        }
        value = (unsigned)packet[2] - 1u;
        base = 3;
    }
    if (!write) {
        packet[base + 1] = 0;
        if (value == 0) {
            packet[base] = legacy ? cdb_brightness_table[CONFIG[2]] : CONFIG[2];
        } else if (value == 1) {
            packet[base] = CONFIG[1];
        } else if (value == 2) {
            packet[base] = legacy && CONFIG[3] == 0 ? 3 : (uint8_t)(4u - CONFIG[3]);
        } else {
            packet[base] = CONFIG[9];
            packet[base + 1] = (uint8_t)~CONFIG[30];
        }
        return;
    }
    uint8_t setting = packet[base];
    if (value == 0) {
        if (legacy) {
            if (setting <= 192) {
                unsigned level = ((unsigned)setting + 20u) / 21u;
                CONFIG[2] = (uint8_t)(level > 9 ? 9 : level);
            }
        } else {
            if (setting > 8) {
                packet[base] = setting = 9;
            }
            CONFIG[2] = setting;
        }
    } else if (value == 1) {
        uint8_t before = CONFIG[1];
        if (setting > 18) {
            setting = 1;
        }
        CONFIG[1] = setting;
        if (before != setting) {
            cdb_rgb_changed();
        }
    } else if (value == 2) {
        CONFIG[3] = (uint8_t)((legacy ? 3u : 4u) - setting);
    } else {
        if (!legacy) {
            CONFIG[5] = 0;
        }
        CONFIG[9] = setting;
        copy(CONFIG + 6, cdb_palette + (unsigned)setting * 3u, 3);
        CONFIG[30] = (uint8_t)~packet[base + 1];
    }
}

void cdb_via_packet(uint8_t packet[32])
{
    unsigned offset, size;
    switch (packet[0]) {
    case 1:
        BYTE(OEM_VIA_FLAGS_OFFSET) |= 8;
        packet[2] = BYTE(OEM_PROTOCOL_VER_OFFSET);
        break;
    case 2:
        copy(packet + 2, OEM_GP_BYTE(OEM_VIA_STATE_OFFSET), 30);
        if ((BYTE(OEM_VIA_FLAGS_OFFSET) & 0x80u) != 0) {
            BYTE(OEM_VIA_FLAGS_OFFSET) &= 0x7f;
            BYTE(OEM_VIA_PENDING_OFFSET) &= 0xfcu;
        }
        break;
    case 5:
        if (packet[1] >= 4 || packet[2] >= 8 || packet[3] >= 16) {
            goto invalid;
        }
        offset = (unsigned)packet[1] * 256u + (unsigned)packet[2] * 32u + (unsigned)packet[3] * 2u;
        keymap_write(offset, packet + 4, 2);
        break;
    case 20:
    case 21:
        if (BYTE(OEM_PROTOCOL_VER_OFFSET) != 11) {
            break;
        }
        if (packet[1] >= 4 || packet[2] >= 8) {
            goto invalid;
        }
        offset = (unsigned)packet[1] * 256u + 224u + (unsigned)packet[2] * 4u +
                 (packet[3] != 0 ? 2u : 0u);
        if (packet[0] == 21) {
            keymap_write(offset, packet + 4, 2);
        } else {
            keymap_read(offset, packet + 4, 2);
        }
        break;
    case 7:
    case 8:
        rgb(packet, (uint8_t)(packet[0] == 7));
        break;
    case 9:
        BYTE(OEM_SAVE_COUNTER_OFFSET) = 0;
        BYTE(OEM_SAVE_FLAGS_OFFSET) |= 2;
        break;
    case 12:
        packet[1] = 16;
        break;
    case 13:
        packet[1] = 2;
        packet[2] = 0;
        break;
    case 14:
        offset = be16(packet + 1);
        size = packet[3];
        /* The app's last request is 28 bytes at offset 504, past the 512-byte
         * buffer; the OEM serves it, so only refuse what cannot leave the
         * 4 KiB macro sector (slot <= 0xC00, offset <= 512, size <= 28). */
        if (offset > CM_BANK_BYTES || size > 28 ||
            MACRO_SLOT > 0xc00 || (MACRO_SLOT & 0x1ffu) != 0) {
            goto invalid;
        }
        if (size != 0) {
            cdb_flash_read(OEM_MACRO_FLASH_BASE + MACRO_SLOT + offset, size, packet + 4);
        }
        break;
    case 15:
        cdb_macro_chunk(packet);
        break;
    case 16:
        break; /* The OEM command acknowledges this without changing data. */
    case 17:
        packet[1] = 4;
        break;
    case 18:
    case 19:
        offset = be16(packet + 1);
        size = packet[3];
        if (size > 28 || offset > 1024 || size > 1024u - offset) {
            goto invalid;
        }
        if (packet[0] == 19) {
            keymap_write(offset, packet + 4, size);
        } else {
            keymap_read(offset, packet + 4, size);
        }
        break;
    default:
        /* Preserve the OEM's version9 fallback response for unsupported
         * commands, including direct GET_KEYCODE (the UI uses GET_BUFFER). */
        packet[0] = 1;
        packet[2] = 9;
        break;
    }
    return;
invalid:
    packet[0] = 0xff;
}
