"""Strict binary Valve KeyValues codec. Preserve types and field ordering."""
from dataclasses import dataclass
import struct


@dataclass
class Node:
    kind: int
    name: str
    value: object

    def get(self, name, default=None):
        child = next((n for n in self.value if n.name.casefold() == name.casefold()), None)
        return child.value if child else default

    def set(self, name, value, kind=1):
        child = next((n for n in self.value if n.name.casefold() == name.casefold()), None)
        if child:
            child.value, child.kind = value, kind
        else:
            self.value.append(Node(kind, name, value))


def loads(data: bytes):
    offset = 0

    def take(n):
        nonlocal offset
        if offset + n > len(data):
            raise ValueError('Truncated shortcuts.vdf. Write cancelled')
        value = data[offset:offset+n]
        offset += n
        return value

    def string():
        nonlocal offset
        end = data.find(b'\0', offset)
        if end < 0:
            raise ValueError('Invalid VDF string')
        result = data[offset:end].decode('utf-8', errors='surrogateescape')
        offset = end + 1
        return result

    def children(depth=0):
        if depth > 32:
            raise ValueError('VDF nesting limit exceeded')
        result = []
        while True:
            kind = take(1)[0]
            if kind == 8:
                return result
            name = string()
            if kind == 0:
                value = children(depth + 1)
            elif kind == 1:
                value = string()
            elif kind == 2:
                value = struct.unpack('<I', take(4))[0]
            elif kind in (3, 4, 6):
                value = take(4)
            elif kind in (7, 10):
                value = take(8)
            elif kind == 5:
                length = take(2)
                value = length + take(struct.unpack('<H', length)[0] * 2)
            else:
                raise ValueError(f'Unsupported VDF type {kind}. Original file was not changed.')
            result.append(Node(kind, name, value))
    result = children()
    if offset != len(data):
        raise ValueError('Unexpected trailing VDF data. Write cancelled.')
    return result


def dumps(nodes):
    result = bytearray()
    def string(value):
        if '\0' in value:
            raise ValueError('VDF string contains a null character')
        return value.encode('utf-8', errors='surrogateescape') + b'\0'
    for node in nodes:
        result.append(node.kind)
        result.extend(string(node.name))
        if node.kind == 0:
            result.extend(dumps(node.value))
        elif node.kind == 1:
            result.extend(string(node.value))
        elif node.kind == 2:
            result.extend(struct.pack('<I', node.value & 0xffffffff))
        else:
            result.extend(node.value)
    result.append(8)
    return bytes(result)


def shortcuts(nodes):
    roots = [n for n in nodes if n.name.casefold() == 'shortcuts' and n.kind == 0]
    if len(roots) != 1:
        raise ValueError('Expected one shortcuts section')
    if any(n.kind != 0 for n in roots[0].value):
        raise ValueError('Invalid shortcut entry')
    return roots[0]
