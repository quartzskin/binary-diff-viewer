import json
import os
from dataclasses import asdict, dataclass

from . import core, pe, strings


@dataclass
class FileInfo:
    path: str
    size: int
    sha256: str


@dataclass
class Report:
    a: FileInfo
    b: FileInfo
    diff: core.ByteDiff
    strings: strings.StringsDiff
    pe: pe.PeComparison | None
    pe_note: str

    @property
    def identical(self):
        return self.a.sha256 == self.b.sha256

    def to_dict(self):
        d = asdict(self)
        d["identical"] = self.identical
        d["diff"]["truncated"] = self.diff.truncated
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self):
        lines = ["# Binary diff", "", "| | A | B |", "|---|---|---|"]
        lines.append(f"| path | `{self.a.path}` | `{self.b.path}` |")
        lines.append(f"| size | {self.a.size} | {self.b.size} |")
        lines.append(f"| sha256 | `{self.a.sha256}` | `{self.b.sha256}` |")
        lines.append("")
        if self.identical:
            lines.append("The files are identical.")
            return "\n".join(lines) + "\n"

        d = self.diff
        lines += [
            f"{d.changed_bytes} bytes differ in {d.range_count} range(s).",
            "",
            "## Changed ranges",
            "",
            "| start | end | length |",
            "|---|---|---|",
        ]
        lines += [f"| 0x{s:x} | 0x{e:x} | {e - s} |" for s, e in d.ranges]
        if d.truncated:
            lines += ["", f"Only the first {len(d.ranges)} ranges are listed."]

        st = self.strings
        lines += ["", "## Strings", "", f"{len(st.removed)} removed, {len(st.added)} added."]
        if st.capped:
            lines.append("Only the first strings of each file were compared.")
        for sign, items in (("-", st.removed), ("+", st.added)):
            if items:
                lines += ["", "```diff"]
                lines += [f"{sign} 0x{off:x} {s}" for off, s in items]
                lines.append("```")

        lines += ["", "## PE sections", ""]
        if self.pe is None:
            lines.append(self.pe_note)
        else:
            for k, (x, y) in self.pe.header_changes.items():
                lines.append(f"- {k}: 0x{x:x} -> 0x{y:x}")
            lines += ["", "| section | status | changed |", "|---|---|---|"]
            lines += [f"| {c.name} | {c.status} | {', '.join(c.fields)} |" for c in self.pe.sections]
        return "\n".join(lines) + "\n"


def compare_files(path_a, path_b, progress=None, cancelled=None):
    def stage(name):
        return lambda done, total: progress(name, done, total) if progress else None

    infos = []
    for p in (path_a, path_b):
        sha = core.sha256_file(p, progress=stage(f"hashing {os.path.basename(p)}"), cancelled=cancelled)
        infos.append(FileInfo(str(p), os.path.getsize(p), sha))
    a, b = infos

    if a.sha256 == b.sha256:
        diff = core.ByteDiff(a.size, b.size)
    else:
        diff = core.diff_bytes(path_a, path_b, progress=stage("comparing bytes"), cancelled=cancelled)
    st = strings.StringsDiff() if diff.identical else strings.diff_strings(path_a, path_b)

    pa, pb = pe.load_pe(path_a), pe.load_pe(path_b)
    if pa and pb:
        comparison, note = pe.compare_pe(pa, pb), ""
    elif pe.pefile is None:
        comparison, note = None, "pefile is not installed, PE comparison skipped."
    else:
        comparison, note = None, "Not both PE files, PE comparison skipped."
    return Report(a, b, diff, st, comparison, note)


def write_report(path, text, force=False):
    mode = "w" if force else "x"
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        f.write(text)
