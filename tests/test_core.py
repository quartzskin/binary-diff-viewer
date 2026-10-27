import hashlib
import os
import tracemalloc

import pytest

from bindiff import core


def test_identical(write):
    data = os.urandom(5000)
    d = core.diff_bytes(write("a", data), write("b", data))
    assert d.identical
    assert d.ranges == []
    assert d.changed_bytes == 0


def test_one_byte_change(write):
    a = bytes(100)
    b = bytearray(a)
    b[42] = 1
    d = core.diff_bytes(write("a", a), write("b", bytes(b)))
    assert d.ranges == [(42, 43)]
    assert d.changed_bytes == 1


def test_adjacent_and_separate_ranges(write):
    a = bytes(50)
    b = bytearray(a)
    b[10:13] = b"\x01\x02\x03"
    b[20] = 9
    d = core.diff_bytes(write("a", a), write("b", bytes(b)))
    assert d.ranges == [(10, 13), (20, 21)]
    assert d.range_count == 2


def test_range_spans_chunk_boundary(write):
    a = bytes(64)
    b = bytearray(a)
    b[14:18] = b"\xff" * 4
    d = core.diff_bytes(write("a", a), write("b", bytes(b)), chunk=16)
    assert d.ranges == [(14, 18)]


def test_truncated(write):
    a = b"abcdefgh"
    d = core.diff_bytes(write("a", a), write("b", a[:5]))
    assert d.ranges == [(5, 8)]
    assert (d.size_a, d.size_b) == (8, 5)


def test_extended_after_change(write):
    d = core.diff_bytes(write("a", b"abcd"), write("b", b"abXdEFG"))
    assert d.ranges == [(2, 3), (4, 7)]


def test_empty_files(write):
    d = core.diff_bytes(write("a", b""), write("b", b""))
    assert d.identical
    d = core.diff_bytes(write("c", b""), write("d", b"xy"))
    assert d.ranges == [(0, 2)]


def test_max_ranges_caps_list_but_not_counts(write):
    a = bytes(100)
    b = bytes(i % 2 for i in range(100))
    d = core.diff_bytes(write("a", a), write("b", b), max_ranges=5)
    assert len(d.ranges) == 5
    assert d.range_count == 50
    assert d.changed_bytes == 50
    assert d.truncated


def test_sha256(write):
    p = write("a", b"hello")
    assert core.sha256_file(p, chunk=2) == hashlib.sha256(b"hello").hexdigest()


def test_cancel(write):
    p = write("a", bytes(100))
    with pytest.raises(core.Cancelled):
        core.diff_bytes(p, write("b", bytes(100)), chunk=10, cancelled=lambda: True)


def test_large_file_is_chunked(tmp_path):
    size = 64 * 1024 * 1024
    block = os.urandom(1 << 20)
    pa, pb = tmp_path / "a.bin", tmp_path / "b.bin"
    for p in (pa, pb):
        with open(p, "wb") as f:
            for _ in range(size >> 20):
                f.write(block)
    with open(pb, "r+b") as f:
        f.seek(40_000_000)
        f.write(b"\x00\x00\x00")
        f.seek(size - 1)
        f.write(bytes([block[-1] ^ 0xFF]))

    tracemalloc.start()
    d = core.diff_bytes(str(pa), str(pb))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert d.range_count == 2
    assert d.ranges[1] == (size - 1, size)
    assert d.ranges[0][0] >= 40_000_000
    assert peak < 16 * 1024 * 1024


def test_hex_rows():
    rows = core.hex_rows(b"abcdefghijklmnopQR", b"abcdefghijklmnopQX", base=0x100)
    assert [r.offset for r in rows] == [0x100, 0x110]
    assert not any(rows[0].diff)
    assert rows[1].diff == [False, True]


def test_hex_rows_uneven_lengths():
    (row,) = core.hex_rows(b"abc", b"a")
    assert row.diff == [False, True, True]
