import os
import glob

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QSpinBox, QDoubleSpinBox, QProgressBar, QListWidget, QFileDialog,
    QMessageBox, QScrollArea, QGridLayout, QCheckBox, QSplitter, QStatusBar,
)

from pdf2image import convert_from_path

from pdf_tool.core import (
    split_pdf_by_pages,
    split_pdf_by_size,
    merge_pdfs,
    extract_pages,
    ensure_output_dir,
    default_output_dir,
)

THUMB_W, THUMB_H = 160, 220


def _find_poppler_path():
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pattern = os.path.join(project_root, "poppler", "poppler_bin", "*", "Library", "bin")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    return None


POPPLER_PATH = _find_poppler_path()


# ── Worker threads ────────────────────────────────────────────────

class PdfWorker(QThread):
    progress = Signal(float)
    task_finished = Signal(bool, str)

    def __init__(self, func, args):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        try:
            ok, msg = self.func(*self.args, progress_callback=self.progress.emit)
        except Exception as e:
            ok, msg = False, str(e)
        self.task_finished.emit(ok, msg)


class ThumbnailWorker(QThread):
    page_ready = Signal(int, QImage)
    done = Signal()

    def __init__(self, pdf_path, version, thumb_w=THUMB_W, thumb_h=THUMB_H):
        super().__init__()
        self.pdf_path = pdf_path
        self.version = version
        self.thumb_w = thumb_w
        self.thumb_h = thumb_h

    def run(self):
        try:
            kwargs = dict(dpi=100, size=(self.thumb_w, self.thumb_h))
            if POPPLER_PATH:
                kwargs["poppler_path"] = POPPLER_PATH
            images = convert_from_path(self.pdf_path, **kwargs)
            for i, pil_img in enumerate(images):
                if self.isInterruptionRequested():
                    return
                img = pil_img.convert("RGB")
                data = img.tobytes("raw", "RGB")
                qimg = QImage(data, img.size[0], img.size[1],
                              img.size[0] * 3, QImage.Format_RGB888).copy()
                self.page_ready.emit(i, qimg)
        except Exception:
            pass
        self.done.emit()


# ── Page thumbnail widget ─────────────────────────────────────────

class PageThumb(QWidget):
    toggled = Signal(int, bool)

    def __init__(self, page_index, pixmap, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        self.cb = QCheckBox(f"第 {page_index + 1} 页")
        self.cb.stateChanged.connect(self._on_toggle)
        layout.addWidget(self.cb, alignment=Qt.AlignCenter)

        self.img_label = QLabel()
        self.img_label.setPixmap(pixmap.scaled(
            THUMB_W, THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.img_label)

        self.setCursor(Qt.PointingHandCursor)
        self._update_style()

    def _on_toggle(self, state):
        self._selected = bool(state)
        self._update_style()
        self.toggled.emit(self.page_index, self._selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.cb.toggle()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet("QFrame{border:2px solid #2196F3; border-radius:4px; background:#E3F2FD;}")
        else:
            self.setStyleSheet("QFrame{border:1px solid #ccc; border-radius:4px; background:#fff;}")

    def set_selected(self, selected):
        self.cb.setChecked(selected)

    @property
    def is_selected(self):
        return self._selected


# ── Shared helpers ────────────────────────────────────────────────

def _pick_pdf_file(parent):
    path, _ = QFileDialog.getOpenFileName(
        parent, "选择PDF文件", "", "PDF Files (*.pdf)")
    return path


def _pick_pdf_files(parent):
    paths, _ = QFileDialog.getOpenFileNames(
        parent, "选择PDF文件", "", "PDF Files (*.pdf)")
    return paths


def _pick_directory(parent):
    return QFileDialog.getExistingDirectory(parent, "选择输出目录")


# ── Split tab ─────────────────────────────────────────────────────

class SplitWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._thumb_worker = None
        self._thumb_version = 0
        self._current_pdf = ""
        self._page_widgets = []
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)

        # Top: file + output
        top = QHBoxLayout()
        grp = QGroupBox("输入PDF文件")
        h = QHBoxLayout(grp)
        self.input_edit = QLineEdit()
        self.input_edit.setReadOnly(True)
        h.addWidget(self.input_edit)
        btn = QPushButton("浏览")
        btn.clicked.connect(self._browse_input)
        h.addWidget(btn)
        top.addWidget(grp, stretch=3)

        grp2 = QGroupBox("输出目录")
        h2 = QHBoxLayout(grp2)
        self.output_edit = QLineEdit()
        h2.addWidget(self.output_edit)
        btn2 = QPushButton("浏览")
        btn2.clicked.connect(lambda: self._browse_dir(self.output_edit))
        h2.addWidget(btn2)
        top.addWidget(grp2, stretch=3)
        outer.addLayout(top)

        # Middle: preview + controls
        splitter = QSplitter(Qt.Horizontal)

        # Preview area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.preview_container = QWidget()
        self.preview_grid = QGridLayout(self.preview_container)
        self.preview_grid.setSpacing(8)
        scroll.setWidget(self.preview_container)
        splitter.addWidget(scroll)

        # Control panel
        ctrl = QWidget()
        cl = QVBoxLayout(ctrl)

        mg = QGroupBox("分割方式")
        mgl = QVBoxLayout(mg)
        self.mode_group = QButtonGroup(self)
        self.rb_pages = QRadioButton("按页数分割")
        self.rb_size = QRadioButton("按文件大小分割")
        self.rb_select = QRadioButton("按选取页面分割")
        self.rb_pages.setChecked(True)
        self.mode_group.addButton(self.rb_pages, 0)
        self.mode_group.addButton(self.rb_size, 1)
        self.mode_group.addButton(self.rb_select, 2)
        mgl.addWidget(self.rb_pages)
        mgl.addWidget(self.rb_size)
        mgl.addWidget(self.rb_select)
        self.mode_group.idClicked.connect(self._toggle_mode)
        cl.addWidget(mg)

        # Params — wrap each label+input in a container for visibility control
        pg = QGroupBox("参数设置")
        pgl = QVBoxLayout(pg)

        self.pages_container = QWidget()
        pc_layout = QVBoxLayout(self.pages_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.addWidget(QLabel("每个文件的页数:"))
        self.spin_pages = QSpinBox()
        self.spin_pages.setRange(1, 9999)
        self.spin_pages.setValue(10)
        pc_layout.addWidget(self.spin_pages)
        pgl.addWidget(self.pages_container)

        self.size_container = QWidget()
        sc_layout = QVBoxLayout(self.size_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.addWidget(QLabel("最大文件大小 (MB):"))
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(0.1, 99999)
        self.spin_size.setValue(20)
        sc_layout.addWidget(self.spin_size)
        pgl.addWidget(self.size_container)

        self.lbl_select_hint = QLabel("选中的页面将合并提取为一个PDF。")
        self.lbl_select_hint.setWordWrap(True)
        pgl.addWidget(self.lbl_select_hint)

        cl.addWidget(pg)

        # Selection shortcuts
        sg = QGroupBox("页面选择")
        sgl = QVBoxLayout(sg)
        for text, fn in [
            ("全选", self._select_all),
            ("全不选", self._select_none),
            ("奇数页", self._select_odd),
            ("偶数页", self._select_even),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            sgl.addWidget(b)
        cl.addWidget(sg)

        cl.addStretch()
        splitter.addWidget(ctrl)
        splitter.setSizes([500, 200])
        outer.addWidget(splitter, stretch=1)

        # Bottom
        bot = QHBoxLayout()
        self.btn_start = QPushButton("开始分割")
        self.btn_start.clicked.connect(self._start)
        bot.addWidget(self.btn_start)
        self.progress = QProgressBar()
        bot.addWidget(self.progress, stretch=1)
        self.status = QLabel()
        bot.addWidget(self.status, stretch=1)
        outer.addLayout(bot)

        self._toggle_mode(0)

    # -- Browse --

    def _browse_input(self):
        path = _pick_pdf_file(self)
        if path:
            self.input_edit.setText(path)
            self.output_edit.setText(default_output_dir(path))
            self._load_pdf(path)

    def _browse_dir(self, edit):
        d = _pick_directory(self)
        if d:
            edit.setText(d)

    # -- Thumbnail loading --

    def _load_pdf(self, path):
        self._clear_thumbnails()
        self._current_pdf = path
        self._thumb_version += 1
        version = self._thumb_version
        self._thumb_worker = ThumbnailWorker(path, version)
        self._thumb_worker.page_ready.connect(
            lambda i, qimg: self._add_thumb(i, qimg, version)
        )
        self._thumb_worker.start()

    def _clear_thumbnails(self):
        for w in self._page_widgets:
            w.setParent(None)
            w.deleteLater()
        self._page_widgets.clear()

    def _add_thumb(self, index, qimage, version):
        if version != self._thumb_version:
            return
        pixmap = QPixmap.fromImage(qimage)
        thumb = PageThumb(index, pixmap)
        cols = 4
        row, col = divmod(index, cols)
        self.preview_grid.addWidget(thumb, row, col)
        self._page_widgets.append(thumb)

    # -- Mode toggle --

    def _toggle_mode(self, mode_id):
        self.pages_container.setVisible(mode_id == 0)
        self.size_container.setVisible(mode_id == 1)
        self.lbl_select_hint.setVisible(mode_id == 2)

    # -- Selection shortcuts --

    def _select_all(self):
        for w in self._page_widgets:
            w.set_selected(True)

    def _select_none(self):
        for w in self._page_widgets:
            w.set_selected(False)

    def _select_odd(self):
        for w in self._page_widgets:
            w.set_selected(w.page_index % 2 == 0)

    def _select_even(self):
        for w in self._page_widgets:
            w.set_selected(w.page_index % 2 == 1)

    # -- Start split --

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        pdf = self._current_pdf
        if not pdf or not os.path.exists(pdf):
            QMessageBox.warning(self, "错误", "请先选择PDF文件。")
            return

        output_dir = self.output_edit.text().strip()
        if not output_dir:
            output_dir = default_output_dir(pdf)
        ensure_output_dir(output_dir)

        mode = self.mode_group.checkedId()
        if mode == 0:
            pages = self.spin_pages.value()
            self._run(split_pdf_by_pages, (pdf, output_dir, pages))
        elif mode == 1:
            size = self.spin_size.value()
            self._run(split_pdf_by_size, (pdf, output_dir, size))
        elif mode == 2:
            selected = [w.page_index for w in self._page_widgets if w.is_selected]
            if not selected:
                QMessageBox.warning(self, "错误", "请至少选择一个页面。")
                return
            self._run(extract_pages, (pdf, output_dir, selected))

    def _run(self, func, args):
        self.btn_start.setEnabled(False)
        self.progress.setValue(0)
        self._worker = PdfWorker(func, args)
        self._worker.progress.connect(lambda v: self.progress.setValue(int(v)))
        self._worker.task_finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, msg):
        self.btn_start.setEnabled(True)
        self.status.setText(msg)
        if ok:
            QMessageBox.information(self, "成功", msg)
            self._reset()
        else:
            QMessageBox.critical(self, "失败", msg)

    def _reset(self):
        self.progress.setValue(0)
        self.status.clear()


# ── Merge tab ─────────────────────────────────────────────────────

class MergeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._thumb_worker = None
        self._thumb_version = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # File list
        grp = QGroupBox("输入PDF文件")
        h = QHBoxLayout(grp)
        self.file_list = QListWidget()
        self.file_list.currentRowChanged.connect(self._preview_selected)
        h.addWidget(self.file_list, stretch=1)

        btns = QVBoxLayout()
        for text, fn in [
            ("添加文件", self._add_files),
            ("移除选中", self._remove_selected),
            ("上移", self._move_up),
            ("下移", self._move_down),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        h.addLayout(btns)
        layout.addWidget(grp, stretch=1)

        # Preview
        self.preview_label = QLabel("点击文件列表中的项目预览")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        layout.addWidget(self.preview_label, stretch=1)

        # Output
        bot = QHBoxLayout()
        fg = QGroupBox("输出文件名 (可选)")
        fh = QHBoxLayout(fg)
        self.filename_edit = QLineEdit()
        fh.addWidget(self.filename_edit)
        bot.addWidget(fg, stretch=2)

        og = QGroupBox("输出目录")
        oh = QHBoxLayout(og)
        self.output_edit = QLineEdit()
        oh.addWidget(self.output_edit)
        ob = QPushButton("浏览")
        ob.clicked.connect(lambda: self._browse_dir(self.output_edit))
        oh.addWidget(ob)
        bot.addWidget(og, stretch=3)
        layout.addLayout(bot)

        # Action
        act = QHBoxLayout()
        self.btn_start = QPushButton("开始合并")
        self.btn_start.clicked.connect(self._start)
        act.addWidget(self.btn_start)
        self.progress = QProgressBar()
        act.addWidget(self.progress, stretch=1)
        self.status = QLabel()
        act.addWidget(self.status, stretch=1)
        layout.addLayout(act)

    def _add_files(self):
        paths = _pick_pdf_files(self)
        existing = {
            self.file_list.item(i).text()
            for i in range(self.file_list.count())
        }
        for p in paths:
            if p not in existing:
                self.file_list.addItem(p)

    def _remove_selected(self):
        rows = sorted(
            {idx.row() for idx in self.file_list.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.file_list.takeItem(row)

    def _move_up(self):
        row = self.file_list.currentRow()
        if row > 0:
            text = self.file_list.takeItem(row).text()
            self.file_list.insertItem(row - 1, text)
            self.file_list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.file_list.currentRow()
        if row < self.file_list.count() - 1:
            text = self.file_list.takeItem(row).text()
            self.file_list.insertItem(row + 1, text)
            self.file_list.setCurrentRow(row + 1)

    def _browse_dir(self, edit):
        d = _pick_directory(self)
        if d:
            edit.setText(d)

    def _preview_selected(self, row):
        if row < 0:
            return
        path = self.file_list.item(row).text()
        if not os.path.exists(path):
            return
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.requestInterruption()
        self._thumb_version += 1
        version = self._thumb_version
        self.preview_label.setText("加载预览...")
        self._thumb_worker = ThumbnailWorker(path, version, 300, 400)
        self._thumb_worker.page_ready.connect(
            lambda i, qimg: self._show_preview(i, qimg, version)
        )
        self._thumb_worker.start()

    def _show_preview(self, index, qimage, version):
        if version != self._thumb_version:
            return
        if index == 0:
            pixmap = QPixmap.fromImage(qimage)
            self.preview_label.setPixmap(pixmap.scaled(
                300, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            ))

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        paths = [
            self.file_list.item(i).text()
            for i in range(self.file_list.count())
        ]
        if not paths:
            QMessageBox.warning(self, "错误", "请添加要合并的PDF文件。")
            return
        if len(paths) < 2:
            QMessageBox.warning(self, "错误", "合并需要至少两个PDF文件。")
            return

        output_dir = self.output_edit.text().strip() or "."
        ensure_output_dir(output_dir)
        output_name = self.filename_edit.text().strip() or None

        self.btn_start.setEnabled(False)
        self.progress.setValue(0)
        self._worker = PdfWorker(merge_pdfs, (paths, output_dir, output_name))
        self._worker.progress.connect(lambda v: self.progress.setValue(int(v)))
        self._worker.task_finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, msg):
        self.btn_start.setEnabled(True)
        self.status.setText(msg)
        if ok:
            QMessageBox.information(self, "成功", msg)
            self.file_list.clear()
            self.filename_edit.clear()
            self.output_edit.clear()
            self.progress.setValue(0)
            self.status.clear()
            self.preview_label.clear()
            self.preview_label.setText("点击文件列表中的项目预览")
        else:
            QMessageBox.critical(self, "失败", msg)


# ── Main window ───────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 分割与合并工具")
        self.setMinimumSize(900, 700)
        self.resize(1050, 750)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self.split_widget = SplitWidget()
        self.merge_widget = MergeWidget()

        tabs.addTab(self.split_widget, "  分割 PDF  ")
        tabs.addTab(self.merge_widget, "  合并 PDF  ")

        self.setStatusBar(QStatusBar())


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
