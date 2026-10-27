import hashlib
import os
import re
from dataclasses import dataclass, field

CHUNK = 1 << 20
MAX_RANGES = 10_000

_NONZERO = re.compile(rb"[^\x00]+")


class Cancelled(Exception):
    pass


@dataclass
class ByteDiff:
    size_a: int
    size_b: int
    ranges: list[tuple[int, int]] = field(default_factory=list)
    range_count: int = 0
    changed_bytes: int = 0

    @property
    def truncated(self):
        return self.range_count > len(self.ranges)

    @property
    def identical(self):
        return self.range_count == 0


class _RangeCollector:
    def __init__(self, limit):
        self.limit = limit
        self.out = ByteDiff(0, 0)
        self._start = None
        self._end = None

    def add(self, start, end):
        if self._start is not None and start == self._end:
            self._end = end
            return
        self.flush()
        self._start, self._end = start, end

    def flush(self):
        if self._start is None:
            return
        self.out.range_count += 1
        self.out.changed_bytes += self._end - self._start
        if len(self.out.ranges) < self.limit:
            self.out.ranges.append((self._start, self._end))
        self._start = None


def sha256_file(path, chunk=CHUNK, progress=None, cancelled=None):
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while block := f.read(chunk):
            if cancelled and cancelled():
                raise Cancelled
            h.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return h.hexdigest()


def diff_bytes(path_a, path_b, chunk=CHUNK, max_ranges=MAX_RANGES, progress=None, cancelled=None):
    size_a = os.path.getsize(path_a)
    size_b = os.path.getsize(path_b)
    common = min(size_a, size_b)
    col = _RangeCollector(max_ranges)
    pos = 0
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        while pos < common:
            if cancelled and cancelled():
                raise Cancelled
            n = min(chunk, common - pos)
            ba = fa.read(n)
            bb = fb.read(n)
            if ba != bb:
                # xor the whole chunk as one int, nonzero runs are the differing bytes
                x = int.from_bytes(ba, "little") ^ int.from_bytes(bb, "little")
                for m in _NONZERO.finditer(x.to_bytes(n, "little")):
                    col.add(pos + m.start(), pos + m.end())
            pos += n
            if progress:
                progress(pos, common)
    if size_a != size_b:
        col.add(common, max(size_a, size_b))
    col.flush()
    col.out.size_a = size_a
    col.out.size_b = size_b
    return col.out


def read_block(path, offset, length):
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read(length)


@dataclass
class HexRow:
    offset: int
    a: bytes
    b: bytes
    diff: list[bool]


def hex_rows(a, b, base=0, width=16):
    rows = []
    for i in range(0, max(len(a), len(b)), width):
        ra = a[i : i + width]
        rb = b[i : i + width]
        diff = [ra[j : j + 1] != rb[j : j + 1] for j in range(max(len(ra), len(rb)))]
        rows.append(HexRow(base + i, ra, rb, diff))
    return rows
