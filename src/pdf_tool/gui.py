import json
import os
import sys
import subprocess
import glob

if getattr(sys, 'frozen', False) and sys.platform == 'win32':
    _original_popen_init = subprocess.Popen.__init__
    def _popen_init(self, *args, **kwargs):
        kwargs.setdefault('creationflags', 0)
        kwargs['creationflags'] |= subprocess.CREATE_NO_WINDOW
        _original_popen_init(self, *args, **kwargs)
    subprocess.Popen.__init__ = _popen_init

from PySide6.QtCore import Qt, QThread, Signal, QSettings, QEvent
from PySide6.QtGui import QPixmap, QImage, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QSpinBox, QDoubleSpinBox, QProgressBar, QListWidget, QFileDialog,
    QMessageBox, QScrollArea, QGridLayout, QCheckBox, QSplitter, QStatusBar, QDialog,
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
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
        poppler_dir = os.path.join(base, 'poppler')
        if os.path.isdir(poppler_dir):
            return poppler_dir
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


# ── Page preview dialog ────────────────────────────────────────────

class PagePreviewDialog(QDialog):
    def __init__(self, pdf_path, page_index, total_pages, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._current = page_index
        self._total = total_pages
        self._zoom = 1.0
        self._original_pixmap = None
        self.setWindowTitle(f"第 {page_index + 1} / {total_pages} 页 - 页面预览")
        self.resize(800, 1000)
        layout = QVBoxLayout(self)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignCenter)
        self._scroll.setWidget(self._img_label)
        self._scroll.viewport().installEventFilter(self)
        self._drag_start = None
        self._drag_bar_pos = None
        layout.addWidget(self._scroll, stretch=1)

        nav = QHBoxLayout()
        self._btn_prev = QPushButton("上一页")
        self._btn_prev.clicked.connect(self._prev_page)
        nav.addWidget(self._btn_prev)
        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self._page_label, stretch=1)
        self._btn_next = QPushButton("下一页")
        self._btn_next.clicked.connect(self._next_page)
        nav.addWidget(self._btn_next)
        layout.addLayout(nav)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        self._render_page(page_index)

    def _render_page(self, page_index):
        self._current = page_index
        self._page_label.setText(
            f"第 {page_index + 1} / {self._total} 页  ({int(self._zoom * 100)}%)")
        self._btn_prev.setEnabled(page_index > 0)
        self._btn_next.setEnabled(page_index < self._total - 1)
        self._img_label.setText("正在渲染...")

        kwargs = dict(dpi=200, first_page=page_index + 1, last_page=page_index + 1)
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        try:
            images = convert_from_path(self._pdf_path, **kwargs)
            if images:
                pil_img = images[0].convert("RGB")
                data = pil_img.tobytes("raw", "RGB")
                qimg = QImage(data, pil_img.size[0], pil_img.size[1],
                              pil_img.size[0] * 3, QImage.Format_RGB888).copy()
                self._img_label.setPixmap(QPixmap.fromImage(qimg))
                self._original_pixmap = QPixmap.fromImage(qimg)
                if self._zoom != 1.0:
                    new_w = int(self._original_pixmap.width() * self._zoom)
                    new_h = int(self._original_pixmap.height() * self._zoom)
                    self._img_label.setPixmap(self._original_pixmap.scaled(
                        new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self._scroll.verticalScrollBar().setValue(0)
            else:
                self._img_label.setText("无法渲染此页面。")
        except Exception:
            self._img_label.setText("渲染失败。")

    def _prev_page(self):
        if self._current > 0:
            self._render_page(self._current - 1)

    def _next_page(self):
        if self._current < self._total - 1:
            self._render_page(self._current + 1)

    def eventFilter(self, obj, event):
        if obj is self._scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    delta = event.angleDelta().y()
                    factor = 1.15 if delta > 0 else 1 / 1.15
                    new_zoom = max(0.25, min(5.0, self._zoom * factor))
                    if new_zoom != self._zoom:
                        mouse_pos = event.position().toPoint()
                        self._apply_zoom(new_zoom, mouse_pos)
                    return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._drag_start = event.position().toPoint()
                    self._drag_bar_pos = (
                        self._scroll.horizontalScrollBar().value(),
                        self._scroll.verticalScrollBar().value(),
                    )
                    self._scroll.viewport().setCursor(Qt.ClosedHandCursor)
            elif event.type() == QEvent.Type.MouseMove:
                if self._drag_start is not None:
                    delta = event.position().toPoint() - self._drag_start
                    self._scroll.horizontalScrollBar().setValue(
                        self._drag_bar_pos[0] - delta.x())
                    self._scroll.verticalScrollBar().setValue(
                        self._drag_bar_pos[1] - delta.y())
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self._drag_start is not None:
                    self._drag_start = None
                    self._drag_bar_pos = None
                    self._scroll.viewport().setCursor(Qt.ArrowCursor)
        return super().eventFilter(obj, event)

    def _apply_zoom(self, new_zoom, mouse_pos=None):
        if self._original_pixmap is None:
            return
        old_zoom = self._zoom
        self._zoom = new_zoom
        new_w = int(self._original_pixmap.width() * self._zoom)
        new_h = int(self._original_pixmap.height() * self._zoom)
        scaled = self._original_pixmap.scaled(
            new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img_label.setPixmap(scaled)
        if mouse_pos is not None:
            h_bar = self._scroll.horizontalScrollBar()
            v_bar = self._scroll.verticalScrollBar()
            ratio = new_zoom / old_zoom
            new_x = (h_bar.value() + mouse_pos.x()) * ratio - mouse_pos.x()
            new_y = (v_bar.value() + mouse_pos.y()) * ratio - mouse_pos.y()
            h_bar.setValue(int(new_x))
            v_bar.setValue(int(new_y))
        self._page_label.setText(
            f"第 {self._current + 1} / {self._total} 页  ({int(self._zoom * 100)}%)")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self._prev_page()
        elif event.key() == Qt.Key_Right:
            self._next_page()
        else:
            super().keyPressEvent(event)


# ── Page thumbnail widget ─────────────────────────────────────────

class PageThumb(QWidget):
    toggled = Signal(int, bool)
    doubleClicked = Signal(int)

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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.cb.toggle()
            self.doubleClicked.emit(self.page_index)

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

def _pick_pdf_file(parent, start_dir=""):
    path, _ = QFileDialog.getOpenFileName(
        parent, "选择PDF文件", start_dir, "PDF Files (*.pdf)")
    return path


def _pick_pdf_files(parent, start_dir=""):
    paths, _ = QFileDialog.getOpenFileNames(
        parent, "选择PDF文件", start_dir, "PDF Files (*.pdf)")
    return paths


def _pick_directory(parent, start_dir=""):
    return QFileDialog.getExistingDirectory(parent, "选择输出目录", start_dir)


# ── Split tab ─────────────────────────────────────────────────────

class SplitWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._thumb_worker = None
        self._thumb_version = 0
        self._current_pdf = ""
        self._page_widgets = []
        self._settings = None
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
        start = self._last_input_dir()
        path = _pick_pdf_file(self, start)
        if path:
            self.input_edit.setText(path)
            self.output_edit.setText(default_output_dir(path))
            self._load_pdf(path)

    def _browse_dir(self, edit):
        start = edit.text().strip()
        if not start or not os.path.isdir(start):
            start = self._last_input_dir()
        d = _pick_directory(self, start)
        if d:
            edit.setText(d)

    def _last_input_dir(self):
        if self._settings:
            pdf = self._settings.value("split/input_pdf", "")
            if pdf and os.path.exists(pdf):
                return os.path.dirname(pdf)
        return ""

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
        thumb.doubleClicked.connect(self._preview_page)
        cols = 4
        row, col = divmod(index, cols)
        self.preview_grid.addWidget(thumb, row, col)
        self._page_widgets.append(thumb)

    def _preview_page(self, page_index):
        if self._current_pdf:
            total = len(self._page_widgets)
            dlg = PagePreviewDialog(self._current_pdf, page_index, total, self)
            dlg.exec()

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
        self._settings = None
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
        start = self._last_input_dir()
        paths = _pick_pdf_files(self, start)
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
        start = edit.text().strip()
        if not start or not os.path.isdir(start):
            start = self._last_input_dir()
        d = _pick_directory(self, start)
        if d:
            edit.setText(d)

    def _last_input_dir(self):
        if self._settings:
            files_json = self._settings.value("merge/files", "[]")
            try:
                files = json.loads(files_json)
                for f in files:
                    if os.path.exists(f):
                        return os.path.dirname(f)
            except (json.JSONDecodeError, TypeError):
                pass
        return ""

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

        self._settings = QSettings("pdf_tool.ini", QSettings.IniFormat)
        if getattr(sys, 'frozen', False):
            ini_path = os.path.join(os.path.dirname(sys.executable), "pdf_tool.ini")
            self._settings = QSettings(ini_path, QSettings.IniFormat)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self.split_widget = SplitWidget()
        self.merge_widget = MergeWidget()
        self.split_widget._settings = self._settings
        self.merge_widget._settings = self._settings

        tabs.addTab(self.split_widget, "  分割 PDF  ")
        tabs.addTab(self.merge_widget, "  合并 PDF  ")

        self.setStatusBar(QStatusBar())
        self._restore_settings()

    def _save_settings(self):
        s = self._settings
        s.setValue("split/input_pdf", self.split_widget.input_edit.text())
        s.setValue("split/output_dir", self.split_widget.output_edit.text())

        merge_files = [
            self.merge_widget.file_list.item(i).text()
            for i in range(self.merge_widget.file_list.count())
        ]
        s.setValue("merge/files", json.dumps(merge_files, ensure_ascii=False))
        s.setValue("merge/output_dir", self.merge_widget.output_edit.text())
        s.setValue("merge/output_name", self.merge_widget.filename_edit.text())

    def _restore_settings(self):
        s = self._settings

        split_pdf = s.value("split/input_pdf", "")
        split_out = s.value("split/output_dir", "")
        if split_pdf:
            self.split_widget.input_edit.setText(split_pdf)
            if split_out:
                self.split_widget.output_edit.setText(split_out)
            else:
                self.split_widget.output_edit.setText(default_output_dir(split_pdf))
            if os.path.exists(split_pdf):
                self.split_widget._load_pdf(split_pdf)

        merge_files_json = s.value("merge/files", "[]")
        try:
            merge_files = json.loads(merge_files_json)
            for f in merge_files:
                if os.path.exists(f):
                    self.merge_widget.file_list.addItem(f)
        except (json.JSONDecodeError, TypeError):
            pass
        merge_out = s.value("merge/output_dir", "")
        if merge_out:
            self.merge_widget.output_edit.setText(merge_out)
        merge_name = s.value("merge/output_name", "")
        if merge_name:
            self.merge_widget.filename_edit.setText(merge_name)

    def closeEvent(self, event: QCloseEvent):
        self._save_settings()
        super().closeEvent(event)


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
