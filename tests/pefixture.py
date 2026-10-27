import struct


def make_pe(sections, entry=0x1000, timestamp=0x5F000000):
    """Build a tiny PE32 image from [(name, bytes)]. Never meant to run."""
    n = len(sections)
    dos = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    coff = struct.pack("<HHIIIHH", 0x14C, n, timestamp, 0, 0, 224, 0x102)
    opt = struct.pack(
        "<HBB" + "I" * 9 + "H" * 6 + "IIII" + "HH" + "IIII" + "II",
        0x10B, 1, 0, 0, 0, 0, entry, 0x1000, 0x2000, 0x400000, 0x1000, 0x200,
        4, 0, 0, 0, 4, 0, 0, 0x1000 * (n + 1), 0x200, 0, 3, 0, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16,
    )  # fmt: skip
    opt += bytes(16 * 8)
    headers = dos + b"PE\x00\x00" + coff + opt
    raw_ptr = 0x200
    table, body = b"", b""
    for i, (name, data) in enumerate(sections):
        padded = data + bytes(-len(data) % 0x200)
        table += struct.pack(
            "<8sIIIIIIHHI",
            name.encode(),
            len(data),
            0x1000 * (i + 1),
            len(padded),
            raw_ptr,
            0,
            0,
            0,
            0,
            0x60000020,
        )
        body += padded
        raw_ptr += len(padded)
    headers += table
    return headers + bytes(0x200 - len(headers)) + body
