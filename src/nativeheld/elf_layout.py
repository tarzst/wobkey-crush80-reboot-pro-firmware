"""Small strict ELF32 section reader for locally generated RV32 artifacts."""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Section:
    name: str
    kind: int
    flags: int
    address: int
    data: bytes
    alignment: int
    size: int


def sections(data):
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected ELF32 little endian')
    if struct.unpack_from('<H', data, 18)[0] != 243:
        raise ValueError('expected RISC-V ELF machine')
    offset = struct.unpack_from('<I', data, 32)[0]
    width, count, names_index = struct.unpack_from('<HHH', data, 46)
    if width != 40 or count == 0 or names_index >= count or offset + width * count > len(data):
        raise ValueError('invalid ELF section table')
    headers = [struct.unpack_from('<10I', data, offset + i * width) for i in range(count)]
    strings = headers[names_index]
    if strings[1] != 3 or strings[4] + strings[5] > len(data):
        raise ValueError('invalid ELF section names')
    names = data[strings[4]:strings[4] + strings[5]]
    result = []
    for name, kind, flags, address, start, size, link, info, alignment, entsize in headers:
        if name >= len(names) or (kind != 8 and start + size > len(data)):
            raise ValueError('ELF section outside file')
        end = names.find(b'\0', name)
        if end == -1:
            raise ValueError('unterminated ELF section name')
        payload = data[start:start + size] if kind != 8 else b''
        result.append(Section(names[name:end].decode('ascii'), kind, flags, address,
                              payload, alignment, size))
    return result


def symbols(data):
    sections(data)
    offset = struct.unpack_from('<I', data, 32)[0]
    width, count, _ = struct.unpack_from('<HHH', data, 46)
    headers = [struct.unpack_from('<10I', data, offset + i * width) for i in range(count)]
    defined, undefined = {}, []
    for _, kind, _, _, start, size, link, _, _, entsize in headers:
        if kind != 2:
            continue
        if entsize != 16 or size % 16 or link >= count:
            raise ValueError('invalid ELF symbol table')
        str_hdr = headers[link]
        if str_hdr[1] != 3 or str_hdr[4] + str_hdr[5] > len(data):
            raise ValueError('invalid ELF symbol string table')
        strings = data[str_hdr[4]:str_hdr[4] + str_hdr[5]]
        for pos in range(start, start + size, 16):
            st_name, value, _, info, _, shndx = struct.unpack_from('<IIIBBH', data, pos)
            if not st_name:
                continue
            if st_name >= len(strings) or (end := strings.find(b'\0', st_name)) == -1:
                raise ValueError('invalid ELF symbol name')
            name = strings[st_name:end].decode('ascii')
            if shndx == 0:
                undefined.append(name)
            elif (info & 0xf) != 4:  # ignore STT_FILE
                defined[name] = value
    if undefined:
        raise ValueError(f'undefined ELF symbols: {sorted(undefined)}')
    return defined


def audit_gp(data):
    syms = symbols(data)
    expected = syms.get('cdb_oem_common')
    uses = []
    for section in sections(data):
        if not (section.flags & 4 and section.size):
            continue
        pc, code = 0, section.data
        while pc < len(code):
            half = int.from_bytes(code[pc:pc + 2], 'little')
            if half == 0:
                pc += 2
                continue
            if (half & 3) == 3:
                w = int.from_bytes(code[pc:pc + 4], 'little')
                op, rd, rs1, rs2 = w & 0x7f, (w >> 7) & 0x1f, (w >> 15) & 0x1f, (w >> 20) & 0x1f
                regs = ((rd if op not in (0x23, 0x63) else 0),
                        (rs1 if op not in (0x17, 0x37, 0x6f) else 0),
                        (rs2 if op in (0x23, 0x33, 0x63) else 0))
                if 3 in regs:
                    addr = section.address + pc
                    if addr != expected or w != 0x3a11c703:
                        raise ValueError(f'unexpected GP access at {addr:#x}: {w:#010x}')
                    uses.append(addr)
                pc += 4
            else:
                op, f3, r1, r2 = half & 3, (half >> 13) & 7, (half >> 7) & 0x1f, (half >> 2) & 0x1f
                has_gp = (op == 1 and f3 in (0, 2, 3) and r1 == 3) or \
                         (op == 2 and ((f3 != 6 and r1 == 3) or (f3 in (4, 6) and r2 == 3)))
                if has_gp:
                    raise ValueError(f'unexpected compressed GP access at {section.address + pc:#x}: {half:#06x}')
                pc += 2
    if uses != [expected]:
        raise ValueError('missing or duplicated OEM GP resume shim')
    return uses


