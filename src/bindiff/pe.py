import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field

try:
    import pefile
except ImportError:
    pefile = None


@dataclass
class Section:
    name: str
    virtual_size: int
    raw_size: int
    characteristics: int
    entropy: float
    sha256: str


@dataclass
class PeInfo:
    entry_point: int
    timestamp: int
    sections: list[Section]


@dataclass
class SectionChange:
    name: str
    status: str
    fields: list[str] = field(default_factory=list)
    a: Section | None = None
    b: Section | None = None


@dataclass
class PeComparison:
    header_changes: dict[str, tuple[int, int]]
    sections: list[SectionChange]

    @property
    def identical(self):
        return not self.header_changes and all(s.status == "same" for s in self.sections)


def _entropy(data):
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in Counter(data).values())


def load_pe(path):
    if pefile is None:
        return None
    try:
        pe = pefile.PE(path, fast_load=True)
    except (pefile.PEFormatError, OSError):
        return None
    with pe:
        sections = []
        for s in pe.sections:
            data = s.get_data()
            sections.append(
                Section(
                    s.Name.rstrip(b"\x00").decode("latin-1"),
                    s.Misc_VirtualSize,
                    s.SizeOfRawData,
                    s.Characteristics,
                    round(_entropy(data), 3),
                    hashlib.sha256(data).hexdigest(),
                )
            )
        return PeInfo(
            pe.OPTIONAL_HEADER.AddressOfEntryPoint,
            pe.FILE_HEADER.TimeDateStamp,
            sections,
        )


def _pair_sections(a, b):
    # same-named sections are matched in order of appearance
    seen = Counter()
    by_key = {}
    for s in b:
        by_key[(s.name, seen[s.name])] = s
        seen[s.name] += 1
    seen = Counter()
    for s in a:
        key = (s.name, seen[s.name])
        seen[s.name] += 1
        yield s.name, s, by_key.pop(key, None)
    for (name, _), s in by_key.items():
        yield name, None, s


def compare_pe(a, b):
    headers = {}
    if a.entry_point != b.entry_point:
        headers["entry_point"] = (a.entry_point, b.entry_point)
    if a.timestamp != b.timestamp:
        headers["timestamp"] = (a.timestamp, b.timestamp)
    changes = []
    for name, sa, sb in _pair_sections(a.sections, b.sections):
        if sa is None:
            changes.append(SectionChange(name, "added", b=sb))
        elif sb is None:
            changes.append(SectionChange(name, "removed", a=sa))
        else:
            diffs = [
                f
                for f in ("virtual_size", "raw_size", "characteristics", "sha256")
                if getattr(sa, f) != getattr(sb, f)
            ]
            changes.append(SectionChange(name, "changed" if diffs else "same", diffs, sa, sb))
    return PeComparison(headers, changes)
