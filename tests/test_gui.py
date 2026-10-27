import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from bindiff import gui  # noqa: E402
from bindiff.report import compare_files  # noqa: E402


def test_window_loads_report(write):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    a = write("a", bytes(40) + b"hello there" + bytes(5000))
    b = write("b", bytes(40) + b"hello THERE" + bytes(5000))
    win = gui.MainWindow()
    win.load_report(compare_files(a, b))
    assert win.ranges.rowCount() == 1
    assert win.strings.rowCount() == 2
    assert "00000020" in win.hex.left.toPlainText()
    assert win.export_json.isEnabled()
    app.processEvents()
    win.close()
