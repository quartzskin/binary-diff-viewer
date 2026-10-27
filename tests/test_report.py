import json
import subprocess
import sys

import pytest

from bindiff import cli, pe, strings
from bindiff.report import compare_files
from pefixture import make_pe


def test_identical_report(write):
    r = compare_files(write("a", b"same"), write("b", b"same"))
    assert r.identical
    assert "identical" in r.to_markdown()
    assert json.loads(r.to_json())["identical"] is True


def test_non_pe_skips_pe_comparison(write):
    r = compare_files(write("a", b"plain text one"), write("b", b"plain text two"))
    assert r.pe is None
    assert "Not both PE" in r.pe_note
    assert "skipped" in r.to_markdown()


def test_strings_diff(write):
    a = b"\x00\x01hello world\x00\x02same string\x00"
    b = b"\x00\x01goodbye now\x00\x02same string\x00"
    r = compare_files(write("a", a), write("b", b))
    assert [s for _, s in r.strings.removed] == ["hello world"]
    assert [s for _, s in r.strings.added] == ["goodbye now"]


def test_utf16_strings(write):
    p = write("a", b"\xff\xff" + "wide text".encode("utf-16-le") + b"\xff")
    found, _ = strings.extract_strings(p)
    assert found == [(2, "wide text")]


def test_strings_empty_file(write):
    assert strings.extract_strings(write("a", b"")) == ([], False)


@pytest.fixture
def pe_pair(write):
    a = make_pe([(".text", b"\x90" * 300), (".data", b"data"), (".old", b"x")])
    b = make_pe([(".text", b"\x90" * 299 + b"\xcc"), (".data", b"data"), (".new", b"y")], entry=0x1010)
    return write("a.exe", a), write("b.exe", b)


def test_pe_sections(pe_pair):
    r = compare_files(*pe_pair)
    assert r.pe is not None
    status = {c.name: c.status for c in r.pe.sections}
    assert status == {".text": "changed", ".data": "same", ".old": "removed", ".new": "added"}
    assert r.pe.header_changes["entry_point"] == (0x1000, 0x1010)
    text = next(c for c in r.pe.sections if c.name == ".text")
    assert text.fields == ["sha256"]
    assert "| .text | changed | sha256 |" in r.to_markdown()


def test_one_pe_one_not(pe_pair, write):
    r = compare_files(pe_pair[0], write("c", b"MZ not really"))
    assert r.pe is None


def test_truncated_pe_does_not_crash(write):
    assert pe.load_pe(write("a", make_pe([(".text", b"abc")])[:100])) is None


def test_cli_exit_codes_and_reports(write, tmp_path, capsys):
    a, b = write("a", b"abc"), write("b", b"abd")
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    assert cli.main([a, b, "--markdown", str(md), "--json", str(js)]) == 1
    assert "0x2" in md.read_text()
    assert json.loads(js.read_text())["diff"]["ranges"] == [[2, 3]]
    assert cli.main([a, a]) == 0


def test_cli_refuses_overwrite(write, tmp_path, capsys):
    a, b = write("a", b"abc"), write("b", b"abd")
    out = tmp_path / "r.md"
    out.write_text("keep me")
    assert cli.main([a, b, "--markdown", str(out)]) == 2
    assert out.read_text() == "keep me"
    assert cli.main([a, b, "--markdown", str(out), "--force"]) == 1
    assert out.read_text() != "keep me"


def test_cli_never_overwrites_inputs(write, capsys):
    a, b = write("a", b"abc"), write("b", b"abd")
    assert cli.main([a, b, "--json", a, "--force"]) == 2
    assert open(a, "rb").read() == b"abc"


def test_cli_missing_file(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope"), str(tmp_path / "nope2")]) == 2


def test_module_entry(write):
    a = write("a", b"abc")
    out = subprocess.run([sys.executable, "-m", "bindiff", a, a], capture_output=True, text=True)
    assert out.returncode == 0
    assert "identical" in out.stdout
