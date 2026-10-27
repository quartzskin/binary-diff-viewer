import argparse
import os
import sys

from .report import compare_files, write_report


def build_parser():
    p = argparse.ArgumentParser(prog="bindiff", description="Compare two files byte by byte.")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--json", metavar="FILE", help="write a JSON report")
    p.add_argument("--markdown", metavar="FILE", help="write a Markdown report")
    p.add_argument("--force", action="store_true", help="overwrite existing report files")
    p.add_argument("--gui", action="store_true", help="open the two files in the GUI")
    return p


def _same_file(x, y):
    return os.path.normcase(os.path.abspath(x)) == os.path.normcase(os.path.abspath(y))


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import run

        return run(args.a, args.b)

    outputs = [(args.json, "to_json"), (args.markdown, "to_markdown")]
    for out, _ in outputs:
        if not out:
            continue
        if _same_file(out, args.a) or _same_file(out, args.b):
            print(f"bindiff: {out} is one of the inputs", file=sys.stderr)
            return 2
        if os.path.exists(out) and not args.force:
            print(f"bindiff: {out} exists, use --force to overwrite", file=sys.stderr)
            return 2

    try:
        report = compare_files(args.a, args.b)
    except OSError as e:
        print(f"bindiff: {e}", file=sys.stderr)
        return 2

    print(f"A  {report.a.size:>12}  {report.a.sha256}")
    print(f"B  {report.b.size:>12}  {report.b.sha256}")
    if report.identical:
        print("identical")
    else:
        d = report.diff
        print(f"{d.changed_bytes} bytes differ in {d.range_count} range(s)")
        for start, end in d.ranges[:20]:
            print(f"  0x{start:08x}-0x{end:08x}  ({end - start} bytes)")
        if d.range_count > 20:
            print(f"  ... {d.range_count - 20} more")
        print(f"strings: {len(report.strings.removed)} removed, {len(report.strings.added)} added")
        print(f"pe: {report.pe_note or ('same' if report.pe.identical else 'differs')}")

    for out, method in outputs:
        if out:
            write_report(out, getattr(report, method)(), force=args.force)
    return 0 if report.identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
