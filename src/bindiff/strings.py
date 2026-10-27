import difflib
import mmap
import re
from dataclasses import dataclass, field

MIN_LEN = 4
MAX_STRINGS = 10_000
MAX_TEXT = 200

_ASCII = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_LEN)
_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % MIN_LEN)


@dataclass
class StringsDiff:
    removed: list[tuple[int, str]] = field(default_factory=list)
    added: list[tuple[int, str]] = field(default_factory=list)
    count_a: int = 0
    count_b: int = 0
    capped: bool = False


def extract_strings(path, limit=MAX_STRINGS):
    found = []
    with open(path, "rb") as f:
        try:
            data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:
            return found, False
        with data:
            for m in _ASCII.finditer(data):
                found.append((m.start(), m.group().decode("ascii")))
            for m in _UTF16.finditer(data):
                found.append((m.start(), m.group().decode("utf-16-le")))
    found.sort()
    capped = len(found) > limit
    return [(off, s[:MAX_TEXT]) for off, s in found[:limit]], capped


def diff_strings(path_a, path_b, limit=MAX_STRINGS):
    sa, cap_a = extract_strings(path_a, limit)
    sb, cap_b = extract_strings(path_b, limit)
    out = StringsDiff(count_a=len(sa), count_b=len(sb), capped=cap_a or cap_b)
    sm = difflib.SequenceMatcher(None, [s for _, s in sa], [s for _, s in sb])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            out.removed.extend(sa[i1:i2])
        if tag in ("insert", "replace"):
            out.added.extend(sb[j1:j2])
    return out
