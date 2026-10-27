"""Renders docs/screenshot.png from two synthetic PE files, offscreen."""

import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
sys.path.insert(0, str(root / "tests"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from bindiff import gui  # noqa: E402
from bindiff.report import compare_files  # noqa: E402
from pefixture import make_pe  # noqa: E402

text_a = b"\x55\x8b\xec\x83\xec\x10" + b"connect to http://example.test/update\x00" + bytes(range(64)) * 3
text_b = b"\x55\x8b\xec\x83\xec\x20" + b"connect to http://example.test/v2/update\x00" + bytes(range(64)) * 3
text_b = text_b[:100] + b"\xcc\xcc" + text_b[102:]

app = QApplication(sys.argv)

with tempfile.TemporaryDirectory() as tmp:
    a, b = Path(tmp, "sample_v1.exe"), Path(tmp, "sample_v2.exe")
    a.write_bytes(make_pe([(".text", text_a), (".rdata", b"config=1\x00" * 8), (".old", b"legacy")]))
    b.write_bytes(
        make_pe([(".text", text_b), (".rdata", b"config=1\x00" * 8), (".rsrc", b"icon data")], entry=0x1010)
    )

    win = gui.MainWindow()
    win.resize(1400, 700)
    win.path_a.setText(a.name)
    win.path_b.setText(b.name)
    win.load_report(compare_files(str(a), str(b)))
    win.tabs.setCurrentWidget(win.hex)
    win.show()
    app.processEvents()
    out = root / "docs" / "screenshot.png"
    out.parent.mkdir(exist_ok=True)
    win.grab().save(str(out))
    print(out)
