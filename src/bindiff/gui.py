import bisect
import html
import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import core
from .report import compare_files

PAGE = 16 * 512
ADDED = "#1a7f37"
REMOVED = "#b00020"
DIFF_BG = "#ffd0d0"


def mono():
    f = QFont("Consolas")
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(10)
    return f


def _cell(rows_bytes, diff, i):
    if i >= len(rows_bytes):
        return "  "
    text = f"{rows_bytes[i]:02x}"
    return f'<span style="background:{DIFF_BG}">{text}</span>' if diff[i] else text


def _ascii(data, diff):
    out = []
    for i, b in enumerate(data):
        ch = html.escape(chr(b)) if 32 <= b < 127 else "."
        out.append(f'<span style="background:{DIFF_BG}">{ch}</span>' if diff[i] else ch)
    return "".join(out)


def rows_html(rows, side):
    lines = []
    for r in rows:
        data = r.a if side == "a" else r.b
        hexes = " ".join(_cell(data, r.diff, i) for i in range(16))
        lines.append(f'<span style="color:#666666">{r.offset:08x}</span>  {hexes}  {_ascii(data, r.diff)}')
    return '<pre style="margin:0">' + "\n".join(lines) + "</pre>"


class Worker(QObject):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, a, b):
        super().__init__()
        self.a, self.b = a, b
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            rep = compare_files(
                self.a,
                self.b,
                progress=lambda s, d, t: self.progress.emit(s, d, t),
                cancelled=lambda: self._cancel,
            )
        except core.Cancelled:
            self.failed.emit("")
        except Exception as e:
            self.failed.emit(str(e))
        else:
            self.done.emit(rep)


class HexPane(QWidget):
    def __init__(self):
        super().__init__()
        self.report = None
        self.offset = 0
        self.starts = []

        self.left = QTextEdit()
        self.right = QTextEdit()
        for w in (self.left, self.right):
            w.setReadOnly(True)
            w.setFont(mono())
            w.setLineWrapMode(QTextEdit.NoWrap)
        a, b = self.left.verticalScrollBar(), self.right.verticalScrollBar()
        a.valueChanged.connect(b.setValue)
        b.valueChanged.connect(a.setValue)

        self.label = QLabel()
        self.btns = {}
        bar = QHBoxLayout()
        for key, text, fn in (
            ("pp", "< page", lambda: self.goto(self.offset - PAGE)),
            ("np", "page >", lambda: self.goto(self.offset + PAGE)),
            ("pd", "< diff", self.prev_diff),
            ("nd", "diff >", self.next_diff),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            bar.addWidget(btn)
            self.btns[key] = btn
        bar.addWidget(self.label, 1)

        panes = QHBoxLayout()
        panes.addWidget(self.left)
        panes.addWidget(self.right)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addLayout(panes)

    def load(self, report):
        self.report = report
        self.starts = [s for s, _ in report.diff.ranges]
        self.goto(self.starts[0] if self.starts else 0)

    def goto(self, offset):
        r = self.report
        if r is None:
            return
        longest = max(r.a.size, r.b.size)
        offset = max(0, min(offset, max(longest - 1, 0))) // 16 * 16
        self.offset = offset
        a = core.read_block(r.a.path, offset, PAGE)
        b = core.read_block(r.b.path, offset, PAGE)
        rows = core.hex_rows(a, b, offset)
        self.left.setHtml(rows_html(rows, "a"))
        self.right.setHtml(rows_html(rows, "b"))
        self.label.setText(f"0x{offset:x} - 0x{offset + PAGE:x} of 0x{longest:x}")
        self.btns["pp"].setEnabled(offset > 0)
        self.btns["np"].setEnabled(offset + PAGE < longest)

    def next_diff(self):
        i = bisect.bisect_left(self.starts, self.offset + PAGE)
        if i < len(self.starts):
            self.goto(self.starts[i])

    def prev_diff(self):
        i = bisect.bisect_left(self.starts, self.offset)
        if i > 0:
            self.goto(self.starts[i - 1])


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.setFont(mono())
    return t


def _fill(table, rows):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(v)))
    table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Binary Diff Viewer")
        self.resize(1200, 760)
        self.report = None
        self._thread = None
        self._worker = None

        self.path_a = QLineEdit()
        self.path_b = QLineEdit()
        self.go = QPushButton("Compare")
        self.go.clicked.connect(self.start)
        self.stop = QPushButton("Cancel")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel)
        self.export_md = QPushButton("Export Markdown")
        self.export_json = QPushButton("Export JSON")
        for btn, kind in ((self.export_md, "md"), (self.export_json, "json")):
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, k=kind: self.export(k))

        top = QVBoxLayout()
        for label, edit in (("A", self.path_a), ("B", self.path_b)):
            row = QHBoxLayout()
            browse = QPushButton("Browse...")
            browse.clicked.connect(lambda _=False, e=edit: self.browse(e))
            row.addWidget(QLabel(label))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            top.addLayout(row)
        actions = QHBoxLayout()
        for w in (self.go, self.stop, self.export_md, self.export_json):
            actions.addWidget(w)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFormat("")
        actions.addWidget(self.bar, 1)
        top.addLayout(actions)

        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFont(mono())
        self.hex = HexPane()
        self.ranges = _table(["start", "end", "length"])
        self.ranges.cellDoubleClicked.connect(self.jump)
        self.strings = _table(["", "offset", "string"])
        self.sections = _table(["section", "status", "changed", "size A", "size B"])
        self.pe_note = QLabel()

        pe_tab = QWidget()
        pe_lay = QVBoxLayout(pe_tab)
        pe_lay.addWidget(self.pe_note)
        pe_lay.addWidget(self.sections)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.hex, "Hex")
        self.tabs.addTab(self.ranges, "Ranges")
        self.tabs.addTab(self.strings, "Strings")
        self.tabs.addTab(pe_tab, "PE sections")

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(top)
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            edit.setText(path)

    def start(self):
        a, b = self.path_a.text().strip(), self.path_b.text().strip()
        if not a or not b:
            return
        self.go.setEnabled(False)
        self.stop.setEnabled(True)
        self._thread = QThread()
        self._worker = Worker(a, b)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_progress)
        self._worker.done.connect(self.load_report)
        self._worker.failed.connect(self.on_failed)
        for sig in (self._worker.done, self._worker.failed):
            sig.connect(self._thread.quit)
        self._thread.finished.connect(self.on_finished)
        self._thread.start()

    def cancel(self):
        if self._worker:
            self._worker.cancel()

    def on_progress(self, stage, done, total):
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.bar.setFormat(stage)

    def on_failed(self, msg):
        if msg:
            QMessageBox.warning(self, "Compare failed", msg)

    def on_finished(self):
        self.go.setEnabled(True)
        self.stop.setEnabled(False)
        self.bar.setFormat("")
        self.bar.setValue(0)
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = self._worker = None

    def export(self, kind):
        ext, text = ("md", self.report.to_markdown) if kind == "md" else ("json", self.report.to_json)
        path, _ = QFileDialog.getSaveFileName(self, "Export report", f"report.{ext}")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text())
        except OSError as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def jump(self, row, _col):
        start = self.report.diff.ranges[row][0]
        self.hex.goto(start)
        self.tabs.setCurrentWidget(self.hex)

    def load_report(self, r):
        self.report = r
        d = r.diff
        lines = [
            f"A  {r.a.path}",
            f"   {r.a.size} bytes  sha256 {r.a.sha256}",
            f"B  {r.b.path}",
            f"   {r.b.size} bytes  sha256 {r.b.sha256}",
            "",
        ]
        if r.identical:
            lines.append("Files are identical.")
        else:
            lines.append(f"{d.changed_bytes} bytes differ in {d.range_count} range(s).")
            if d.truncated:
                lines.append(f"Only the first {len(d.ranges)} ranges are kept.")
            lines.append(f"Strings: {len(r.strings.removed)} removed, {len(r.strings.added)} added.")
        self.summary.setPlainText("\n".join(lines))

        self.hex.load(r)
        _fill(self.ranges, [(f"0x{s:x}", f"0x{e:x}", e - s) for s, e in d.ranges])
        _fill(
            self.strings,
            [("-", f"0x{o:x}", s) for o, s in r.strings.removed]
            + [("+", f"0x{o:x}", s) for o, s in r.strings.added],
        )
        for i in range(self.strings.rowCount()):
            self.strings.item(i, 0).setForeground(QColor(REMOVED if i < len(r.strings.removed) else ADDED))

        if r.pe is None:
            self.pe_note.setText(r.pe_note)
            _fill(self.sections, [])
        else:
            hdr = "; ".join(f"{k} 0x{x:x} -> 0x{y:x}" for k, (x, y) in r.pe.header_changes.items())
            self.pe_note.setText(hdr or "Headers match.")
            _fill(
                self.sections,
                [
                    (
                        c.name,
                        c.status,
                        ", ".join(c.fields),
                        c.a.raw_size if c.a else "",
                        c.b.raw_size if c.b else "",
                    )
                    for c in r.pe.sections
                ],
            )
        self.export_md.setEnabled(True)
        self.export_json.setEnabled(True)


def run(a=None, b=None):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    if a and b:
        win.path_a.setText(a)
        win.path_b.setText(b)
    win.show()
    if a and b:
        win.start()
    return app.exec()


def main():
    return run()
