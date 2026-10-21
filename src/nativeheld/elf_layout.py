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
