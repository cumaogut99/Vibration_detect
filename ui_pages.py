"""
ui_pages.py — Tum sayfa widget'lari.

Sayfalar:
  PageDataManagement  — Veri yukleme + yuklenmis kanallari listele/filtrele
  PageEngineConfig    — engine_config tanimlarini goster
  PageAnalysis        — Tek kanal goruntuleme veya iki kanal karsilastirma
  PageLog             — Genel uygulama logu
"""

import logging
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QComboBox, QLineEdit, QHeaderView,
    QMessageBox, QTextEdit, QRadioButton, QButtonGroup,
    QStackedWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from ui_worker import (
    LoadChannelWorker, LoadMaxHoldWorker,
    CompareChannelsWorker, SingleChannelWorker,
)
from ui_widgets import (
    HealthScoreDial, FilePickerRow,
    LoadingOverlay, LogPanel, MatplotlibCanvas, ChannelStore,
    WaterfallControlBar, ChannelEditDialog,
)
from models import DataType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)

    if title:
        hdr = QFrame()
        hdr.setObjectName("cardHeader")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        hl.addWidget(lbl)
        cl.addWidget(hdr)

    body = QVBoxLayout()
    body.setContentsMargins(16, 12, 16, 16)
    body.setSpacing(10)
    cl.addLayout(body)
    return card, body


def _field_row(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    lbl = QLabel(label)
    lbl.setObjectName("fieldLabel")
    lbl.setFixedWidth(130)
    row.addWidget(lbl)
    row.addWidget(widget, stretch=1)
    return row


def _make_table(headers: list[str]) -> QTableWidget:
    tbl = QTableWidget(0, len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QTableWidget.NoEditTriggers)
    tbl.setAlternatingRowColors(True)
    tbl.setSelectionBehavior(QTableWidget.SelectRows)
    return tbl


def _table_item(text: str, color: Optional[str] = None, bold: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    if color:
        item.setForeground(QColor(color))
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    return item


def _severity_color(sev: str) -> str:
    return {"Critical": "#f85149", "Warning": "#d29922"}.get(sev, "#3fb950")


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: VERI YONETIMI
# ─────────────────────────────────────────────────────────────────────────────

class PageDataManagement(QWidget):
    """Veri yukleme + iki sekmeli kanal listesi sayfasi.

    Sol tarafta iki kart bulunur:
      - Waterfall / OT verisi yukle (mevcut akis)
      - FFT Max Hold verisi yukle (cok-kanalli tek CSV)

    Sag tarafta iki sekme bulunur:
      - Waterfall / OT kanallari
      - FFT Max Hold kanallari

    Her listede her satir icin Duzenle ve Kaldir butonlari vardir.
    """

    log_message = Signal(str, str)   # (msg, level)

    def __init__(self, store: ChannelStore, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._store = store
        self._wf_worker: Optional[LoadChannelWorker] = None
        self._mh_worker: Optional[LoadMaxHoldWorker] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        outer.setSpacing(12)

        # Iki sutunlu yerlesim — sol: iki yukleme karti, sag: sekmeli liste
        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, stretch=1)

        # ── Sol: iki ust uste kart ────────────────────────────────────────
        left_wrap = QVBoxLayout()
        left_wrap.setSpacing(14)
        cols.addLayout(left_wrap, stretch=0)

        wf_card = self._build_waterfall_upload_card()
        mh_card = self._build_max_hold_upload_card()
        wf_card.setFixedWidth(420)
        mh_card.setFixedWidth(420)

        left_wrap.addWidget(wf_card)
        left_wrap.addWidget(mh_card)
        left_wrap.addStretch()

        # ── Sag: sekmeli kanal listeleri ──────────────────────────────────
        right_wrap = QVBoxLayout()
        right_wrap.setSpacing(14)
        cols.addLayout(right_wrap, stretch=1)

        list_card, list_body = _card("🗂️  Yuklenmis Kanallar")

        self._list_tabs = QTabWidget()
        self._list_tabs.setObjectName("plotTabs")
        list_body.addWidget(self._list_tabs, stretch=1)

        # Waterfall / OT sekmesi
        self._wf_tab_widget, self._wf_filter, self._wf_table, self._wf_count = (
            self._build_channel_list_tab(
                placeholder="Motor ID, lokasyon veya eksene gore ara...",
                headers=[
                    "Kanal", "Motor ID", "Lokasyon", "Eksen",
                    "Run ID", "RPM Araligi", "Slice", "Duzenle", "Kaldir",
                ],
            )
        )
        self._list_tabs.addTab(self._wf_tab_widget, "🌊  Waterfall / OT")

        # FFT Max Hold sekmesi
        self._mh_tab_widget, self._mh_filter, self._mh_table, self._mh_count = (
            self._build_channel_list_tab(
                placeholder="Motor ID, kanal adi veya eksene gore ara...",
                headers=[
                    "Kanal", "Motor ID", "Lokasyon", "Eksen",
                    "Run ID", "Freq Araligi", "N", "Duzenle", "Kaldir",
                ],
            )
        )
        self._list_tabs.addTab(self._mh_tab_widget, "📈  FFT Max Hold")

        right_wrap.addWidget(list_card, stretch=1)

        # Store sinyallerine bagla — her degisimde her iki tabloyu yeniden cizdir
        self._store.channel_added.connect(self._on_store_changed)
        self._store.channel_removed.connect(self._on_store_changed)

        self._overlay = LoadingOverlay(self)

        # Ilk doldurma
        self._rebuild_tables()

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Yukleme kartlari ──────────────────────────────────────────────────

    def _build_waterfall_upload_card(self) -> QFrame:
        card, body = _card("⬆️  Waterfall / OT Verisi Yukle")

        self._wf_picker = FilePickerRow("Veri dosyasi:")
        body.addWidget(self._wf_picker)

        eng_edit = QLineEdit()
        eng_edit.setPlaceholderText("ENG-042")
        self._wf_engine_id = eng_edit
        body.addLayout(_field_row("Motor ID:", eng_edit))

        run_edit = QLineEdit()
        run_edit.setPlaceholderText("RUN-001")
        run_edit.setText("RUN-001")
        self._wf_run_id = run_edit
        body.addLayout(_field_row("Run ID:", run_edit))

        from engine_config import LOCATION_CODES, LOCATION_NAMES
        sensor_combo = QComboBox()
        for code in LOCATION_CODES:
            sensor_combo.addItem(f"{code}  —  {LOCATION_NAMES[code]}", code)
        self._wf_sensor_combo = sensor_combo
        body.addLayout(_field_row("Sensor lokasyonu:", sensor_combo))

        axis_combo = QComboBox()
        axis_combo.addItems(["X", "Y", "Z"])
        self._wf_axis_combo = axis_combo
        body.addLayout(_field_row("Eksen:", axis_combo))

        self._wf_load_btn = QPushButton("➕  Kanali Yukle")
        self._wf_load_btn.setObjectName("btnPrimary")
        self._wf_load_btn.setFixedHeight(40)
        self._wf_load_btn.clicked.connect(self._load_waterfall_channel)
        body.addWidget(self._wf_load_btn)

        self._wf_picker.file_selected.connect(self._on_wf_file_selected)
        return card

    def _build_max_hold_upload_card(self) -> QFrame:
        card, body = _card("⬆️  FFT Max Hold Verisi Yukle")

        hint = QLabel(
            "Cok-kanalli CSV. Her sutun ayri kanal olarak yuklenir;\n"
            "lokasyon ve eksen sutun basligindan tahmin edilir,\n"
            "listede her zaman duzenlenebilir."
        )
        hint.setObjectName("fieldLabel")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._mh_picker = FilePickerRow(
            "Veri dosyasi:",
            file_filter="CSV Dosyalari (*.csv);;Tum Dosyalar (*)",
        )
        body.addWidget(self._mh_picker)

        eng_edit = QLineEdit()
        eng_edit.setPlaceholderText("ENG-042")
        self._mh_engine_id = eng_edit
        body.addLayout(_field_row("Motor ID:", eng_edit))

        run_edit = QLineEdit()
        run_edit.setPlaceholderText("RUN-001")
        run_edit.setText("RUN-001")
        self._mh_run_id = run_edit
        body.addLayout(_field_row("Run ID:", run_edit))

        self._mh_load_btn = QPushButton("➕  Kanallari Yukle")
        self._mh_load_btn.setObjectName("btnPrimary")
        self._mh_load_btn.setFixedHeight(40)
        self._mh_load_btn.clicked.connect(self._load_max_hold_channels)
        body.addWidget(self._mh_load_btn)

        self._mh_picker.file_selected.connect(self._on_mh_file_selected)
        return card

    # ── Liste sekmesi yardimci ─────────────────────────────────────────────

    def _build_channel_list_tab(self, placeholder: str, headers: list[str]):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        filter_row = QHBoxLayout()
        flt_lbl = QLabel("🔎  Filtrele:")
        flt_lbl.setObjectName("fieldLabel")
        filter_row.addWidget(flt_lbl)
        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText(placeholder)
        filter_row.addWidget(filter_edit, stretch=1)
        count_label = QLabel("0 kanal")
        count_label.setObjectName("fieldLabel")
        filter_row.addWidget(count_label)
        v.addLayout(filter_row)

        tbl = _make_table(headers)
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(headers)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        v.addWidget(tbl, stretch=1)

        filter_edit.textChanged.connect(lambda _t: self._rebuild_tables())
        return wrap, filter_edit, tbl, count_label

    # ── Dosya secimi auto-fill ────────────────────────────────────────────

    def _on_wf_file_selected(self, path: str):
        from importers import parse_filename
        parsed = parse_filename(Path(path))
        if not parsed:
            return
        self._wf_engine_id.setText(parsed["engine_id"])
        self._wf_run_id.setText(parsed["run_id"])
        loc = parsed["location"]
        for i in range(self._wf_sensor_combo.count()):
            if self._wf_sensor_combo.itemData(i) == loc:
                self._wf_sensor_combo.setCurrentIndex(i)
                break
        idx_a = self._wf_axis_combo.findText(parsed["axis"])
        if idx_a >= 0:
            self._wf_axis_combo.setCurrentIndex(idx_a)

    def _on_mh_file_selected(self, path: str):
        from importers import parse_filename
        parsed = parse_filename(Path(path))
        if parsed:
            self._mh_engine_id.setText(parsed["engine_id"])
            self._mh_run_id.setText(parsed["run_id"])

    # ── Waterfall yukleme ─────────────────────────────────────────────────

    def _load_waterfall_channel(self):
        if not self._wf_picker.path():
            QMessageBox.warning(self, "Eksik giris", "Lutfen veri dosyasi secin.")
            return
        if not self._wf_engine_id.text().strip():
            QMessageBox.warning(self, "Eksik giris", "Motor ID giriniz.")
            return

        loc_code = self._wf_sensor_combo.currentData() \
            or self._wf_sensor_combo.currentText().split()[0]
        self._wf_worker = LoadChannelWorker(
            path            = self._wf_picker.path(),
            engine_id       = self._wf_engine_id.text().strip(),
            run_id          = self._wf_run_id.text().strip() or "RUN-001",
            sensor_location = loc_code,
            axis            = self._wf_axis_combo.currentText(),
        )
        self._wf_worker.progress.connect(lambda m: self.log_message.emit(m, "INFO"))
        self._wf_worker.finished.connect(self._on_wf_load_done)
        self._wf_worker.error.connect(self._on_wf_load_error)

        self._wf_load_btn.setEnabled(False)
        self._overlay.show_loading(
            "Kanal yukleniyor...", Path(self._wf_picker.path()).name,
        )
        self._wf_worker.start()

    def _on_wf_load_done(self, run):
        self._overlay.hide_loading()
        self._wf_load_btn.setEnabled(True)
        key = self._store.add(run)
        self.log_message.emit(f"✓ Kanal eklendi: {key}", "SUCCESS")

    def _on_wf_load_error(self, msg: str):
        self._overlay.hide_loading()
        self._wf_load_btn.setEnabled(True)
        self.log_message.emit(f"✕ Yukleme hatasi: {msg.splitlines()[0]}", "ERROR")
        QMessageBox.critical(self, "Yukleme Hatasi", msg[:400])

    # ── FFT Max Hold yukleme ──────────────────────────────────────────────

    def _load_max_hold_channels(self):
        if not self._mh_picker.path():
            QMessageBox.warning(self, "Eksik giris",
                                "Lutfen FFT Max Hold dosyasini secin.")
            return
        if not self._mh_engine_id.text().strip():
            QMessageBox.warning(self, "Eksik giris", "Motor ID giriniz.")
            return

        self._mh_worker = LoadMaxHoldWorker(
            path      = self._mh_picker.path(),
            engine_id = self._mh_engine_id.text().strip(),
            run_id    = self._mh_run_id.text().strip() or "RUN-001",
        )
        self._mh_worker.progress.connect(lambda m: self.log_message.emit(m, "INFO"))
        self._mh_worker.finished.connect(self._on_mh_load_done)
        self._mh_worker.error.connect(self._on_mh_load_error)

        self._mh_load_btn.setEnabled(False)
        self._overlay.show_loading(
            "Max Hold kanallari yukleniyor...",
            Path(self._mh_picker.path()).name,
        )
        self._mh_worker.start()

    def _on_mh_load_done(self, runs):
        self._overlay.hide_loading()
        self._mh_load_btn.setEnabled(True)
        keys = [self._store.add(r) for r in runs]
        self.log_message.emit(
            f"✓ {len(keys)} Max Hold kanali eklendi", "SUCCESS",
        )
        # Eklenen kanallar genelde Max Hold sekmesinde — kullaniciyi oraya gotur
        self._list_tabs.setCurrentIndex(1)

    def _on_mh_load_error(self, msg: str):
        self._overlay.hide_loading()
        self._mh_load_btn.setEnabled(True)
        self.log_message.emit(f"✕ Max Hold yukleme hatasi: {msg.splitlines()[0]}", "ERROR")
        QMessageBox.critical(self, "Yukleme Hatasi", msg[:400])

    # ── Tablo yonetimi ────────────────────────────────────────────────────

    def _on_store_changed(self, *_args):
        self._rebuild_tables()

    def _rebuild_tables(self):
        self._rebuild_waterfall_table()
        self._rebuild_max_hold_table()

    def _rebuild_waterfall_table(self):
        tbl   = self._wf_table
        query = self._wf_filter.text().strip().lower()
        tbl.setRowCount(0)

        for key, run in self._store.items():
            if run.data_type == DataType.FFT_MAX_HOLD:
                continue
            if query and query not in key.lower():
                continue

            row = tbl.rowCount()
            tbl.insertRow(row)
            rpm_lo, rpm_hi = run.rpm_range
            tbl.setItem(row, 0, _table_item(key, "#e6edf3"))
            tbl.setItem(row, 1, _table_item(run.engine_id, "#58a6ff", bold=True))
            tbl.setItem(row, 2, _table_item(run.sensor_location))
            tbl.setItem(row, 3, _table_item(run.axis))
            tbl.setItem(row, 4, _table_item(run.run_id))
            tbl.setItem(row, 5, _table_item(f"{rpm_lo:.0f}–{rpm_hi:.0f}"))
            tbl.setItem(row, 6, _table_item(str(run.n_slices)))
            tbl.setCellWidget(row, 7, self._make_edit_btn(key, with_location_combo=True))
            tbl.setCellWidget(row, 8, self._make_remove_btn(key))

        self._wf_count.setText(f"{tbl.rowCount()} kanal")

    def _rebuild_max_hold_table(self):
        tbl   = self._mh_table
        query = self._mh_filter.text().strip().lower()
        tbl.setRowCount(0)

        for key, run in self._store.items():
            if run.data_type != DataType.FFT_MAX_HOLD:
                continue
            if query and query not in key.lower():
                continue

            row = tbl.rowCount()
            tbl.insertRow(row)
            freqs = run.frequencies
            f_lo  = float(freqs.min()) if freqs.size else 0.0
            f_hi  = float(freqs.max()) if freqs.size else 0.0
            tbl.setItem(row, 0, _table_item(key, "#e6edf3"))
            tbl.setItem(row, 1, _table_item(run.engine_id, "#58a6ff", bold=True))
            tbl.setItem(row, 2, _table_item(run.sensor_location))
            tbl.setItem(row, 3, _table_item(run.axis))
            tbl.setItem(row, 4, _table_item(run.run_id))
            tbl.setItem(row, 5, _table_item(f"{f_lo:.0f}–{f_hi:.0f} Hz"))
            tbl.setItem(row, 6, _table_item(str(int(freqs.size))))
            tbl.setCellWidget(row, 7, self._make_edit_btn(key, with_location_combo=False))
            tbl.setCellWidget(row, 8, self._make_remove_btn(key))

        self._mh_count.setText(f"{tbl.rowCount()} kanal")

    def _make_remove_btn(self, key: str) -> QPushButton:
        btn = QPushButton("🗑  Kaldir")
        btn.setObjectName("btnBrowse")
        btn.clicked.connect(lambda _c=False, k=key: self._store.remove(k))
        return btn

    def _make_edit_btn(self, key: str, with_location_combo: bool) -> QPushButton:
        btn = QPushButton("✏  Duzenle")
        btn.setObjectName("btnBrowse")
        btn.clicked.connect(
            lambda _c=False, k=key, lc=with_location_combo: self._edit_channel(k, lc)
        )
        return btn

    def _edit_channel(self, key: str, with_location_combo: bool):
        run = self._store.get(key)
        if run is None:
            return

        loc_options = None
        if with_location_combo:
            from engine_config import LOCATION_CODES, LOCATION_NAMES
            loc_options = [(c, LOCATION_NAMES[c]) for c in LOCATION_CODES]

        result = ChannelEditDialog.run(
            self,
            engine_id=run.engine_id,
            run_id=run.run_id,
            sensor_location=run.sensor_location,
            axis=run.axis,
            location_options=loc_options,
        )
        if result is None:
            return

        new_key = self._store.update(
            key,
            engine_id       = result["engine_id"],
            run_id          = result["run_id"],
            sensor_location = result["sensor_location"],
            axis            = result["axis"],
        )
        if new_key != key:
            self.log_message.emit(
                f"✎  Kanal guncellendi: {key} -> {new_key}", "INFO",
            )


# ─────────────────────────────────────────────────────────────────────────────
#  WATERFALL TAB  (control bar + scrollable canvas + nav toolbar)
# ─────────────────────────────────────────────────────────────────────────────

class WaterfallTab(QWidget):
    """Kontrol cubugu (Hz/RPM aralik) + matplotlib canvas paketi.

    `render_fn(freq_min, freq_max, rpm_min, rpm_max)` cagrildiginda yeni bir
    `Figure` dondurmeli (veya kaynak run yoksa `None`).
    """

    def __init__(self, render_fn, parent=None,
                 default_freq_max: float = 3000.0):
        super().__init__(parent)
        self._render_fn = render_fn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._control = WaterfallControlBar(
            self, default_freq_max=default_freq_max,
        )
        self._control.refresh_requested.connect(self._on_refresh)
        layout.addWidget(self._control)

        self._canvas = MatplotlibCanvas(self, show_toolbar=True)
        layout.addWidget(self._canvas, stretch=1)

    def render(self, freq_min=None, freq_max=None,
               rpm_min=None, rpm_max=None) -> None:
        fig = self._render_fn(freq_min, freq_max, rpm_min, rpm_max)
        if fig is not None:
            self._canvas.set_figure(fig)

    def set_rpm_range(self, lo: float, hi: float) -> None:
        self._control.set_rpm_range(lo, hi)

    def _on_refresh(self, freq_min, freq_max, rpm_min, rpm_max):
        self.render(freq_min, freq_max, rpm_min, rpm_max)


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: ANALIZ  (tek kanal goruntuleme + iki kanal karsilastirma)
# ─────────────────────────────────────────────────────────────────────────────

class PageAnalysis(QWidget):
    """Tek kanal goruntuleme + iki kanal karsilastirma sayfasi."""

    log_message = Signal(str, str)

    def __init__(self, store: ChannelStore, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._store = store
        self._worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        outer.setSpacing(10)

        # ── Mod + Motor + Kanal secimleri tek satirda ─────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        outer.addLayout(top_row)

        # Mod secici
        self._rb_single  = QRadioButton("Tek Kanal")
        self._rb_compare = QRadioButton("Karsilastirma")
        self._rb_single.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._rb_single, 0)
        self._mode_group.addButton(self._rb_compare, 1)
        self._mode_group.idToggled.connect(self._on_mode_changed)

        top_row.addWidget(self._rb_single)
        top_row.addWidget(self._rb_compare)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(28)
        sep.setStyleSheet("color:#30363d;")
        top_row.addWidget(sep)

        # Modlara gore farkli secici grubu
        self._selector_stack = QStackedWidget()
        top_row.addWidget(self._selector_stack, stretch=1)

        # ── Tek kanal modu: Motor + Kanal ───────────────────────────────
        single_wrap = QWidget()
        sw_l = QHBoxLayout(single_wrap)
        sw_l.setContentsMargins(0, 0, 0, 0)
        sw_l.setSpacing(8)

        sw_l.addWidget(self._mklabel("Motor:"))
        self._single_motor = QComboBox()
        self._single_motor.setMinimumWidth(120)
        self._single_motor.setMaximumWidth(160)
        self._single_motor.currentTextChanged.connect(self._on_single_motor_changed)
        sw_l.addWidget(self._single_motor)

        sw_l.addWidget(self._mklabel("Kanal:"))
        self._single_combo = QComboBox()
        self._single_combo.setMinimumWidth(220)
        self._single_combo.setMaximumWidth(320)
        sw_l.addWidget(self._single_combo)
        sw_l.addStretch()
        self._selector_stack.addWidget(single_wrap)

        # ── Karsilastirma modu: Ref Motor + Ref Kanal | Ana Motor + Ana Kanal
        compare_wrap = QWidget()
        cw_l = QHBoxLayout(compare_wrap)
        cw_l.setContentsMargins(0, 0, 0, 0)
        cw_l.setSpacing(8)

        cw_l.addWidget(self._mklabel("Ref Motor:"))
        self._ref_motor = QComboBox()
        self._ref_motor.setMinimumWidth(110)
        self._ref_motor.setMaximumWidth(150)
        self._ref_motor.currentTextChanged.connect(self._on_ref_motor_changed)
        cw_l.addWidget(self._ref_motor)

        cw_l.addWidget(self._mklabel("Ref Kanal:"))
        self._ref_combo = QComboBox()
        self._ref_combo.setMinimumWidth(180)
        self._ref_combo.setMaximumWidth(240)
        cw_l.addWidget(self._ref_combo)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedHeight(28)
        sep2.setStyleSheet("color:#30363d;")
        cw_l.addWidget(sep2)

        cw_l.addWidget(self._mklabel("Ana Motor:"))
        self._main_motor = QComboBox()
        self._main_motor.setMinimumWidth(110)
        self._main_motor.setMaximumWidth(150)
        self._main_motor.currentTextChanged.connect(self._on_main_motor_changed)
        cw_l.addWidget(self._main_motor)

        cw_l.addWidget(self._mklabel("Ana Kanal:"))
        self._main_combo = QComboBox()
        self._main_combo.setMinimumWidth(180)
        self._main_combo.setMaximumWidth(240)
        cw_l.addWidget(self._main_combo)
        cw_l.addStretch()
        self._selector_stack.addWidget(compare_wrap)

        # Eylem butonu — comboboxlarin sagi
        self._single_run_btn = QPushButton("▶  Goruntule")
        self._single_run_btn.setObjectName("btnPrimary")
        self._single_run_btn.clicked.connect(self._run_single)
        self._compare_run_btn = QPushButton("▶  Karsilastir")
        self._compare_run_btn.setObjectName("btnPrimary")
        self._compare_run_btn.clicked.connect(self._run_compare)
        top_row.addWidget(self._single_run_btn)
        top_row.addWidget(self._compare_run_btn)

        # ── Sonuc bolumu: sol grafik tablari, sag tani panel ───────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        outer.addWidget(splitter, stretch=1)

        # Grafik tablari
        self._plot_tabs = QTabWidget()
        self._plot_tabs.setObjectName("plotTabs")
        splitter.addWidget(self._plot_tabs)

        # Aktif run referanslari — render_fn'ler bunlari okur
        self._cur_single_run = None
        self._cur_meas_run   = None
        self._cur_ref_run    = None

        # Waterfall sekmeleri (kontrol cubugu + canvas + nav araç çubuğu)
        self._main_wf_tab  = WaterfallTab(self._render_main_wf)
        self._ref_wf_tab   = WaterfallTab(self._render_ref_wf)
        self._ratio_wf_tab = WaterfallTab(self._render_ratio_wf)

        # Order genlikleri ve tani karti — order grid taller -> scrollable
        self._canvas_orders = MatplotlibCanvas(show_toolbar=True, scrollable=True)
        self._canvas_card   = MatplotlibCanvas(show_toolbar=False)

        # Tab indeksleri runtime'da yeniden duzenlenir
        self._plot_tabs.addTab(self._main_wf_tab,  "🌊  Waterfall")
        self._plot_tabs.addTab(self._canvas_orders,"📊  Order Genlikleri")

        # Tani paneli
        diag_scroll = QScrollArea()
        diag_scroll.setWidgetResizable(True)
        diag_scroll.setFrameShape(QFrame.NoFrame)
        self._diag_widget = DiagnosisPanel()
        diag_scroll.setWidget(self._diag_widget)
        splitter.addWidget(diag_scroll)
        self._diag_scroll = diag_scroll

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Store sinyallerine baglan
        self._store.channel_added.connect(self._refresh_combos)
        self._store.channel_removed.connect(self._refresh_combos)

        # Modun varsayilan gorunumu
        self._on_mode_changed(0, True)

        self._overlay = LoadingOverlay(self)

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Mod degisimi: tab yerlesimi ve panel/buton gorunurlugu ─────────────
    def _on_mode_changed(self, idx: int, checked: bool):
        if not checked:
            return
        self._selector_stack.setCurrentIndex(idx)

        # Buton gorunurlugu
        self._single_run_btn.setVisible(idx == 0)
        self._compare_run_btn.setVisible(idx == 1)

        # Tablari sifirla
        while self._plot_tabs.count():
            self._plot_tabs.removeTab(0)

        if idx == 0:
            # Tek kanal: sadece waterfall + order genlikleri (referanssiz)
            self._plot_tabs.addTab(self._main_wf_tab, "🌊  Waterfall")
            self._plot_tabs.addTab(self._canvas_orders, "📊  Order Genlikleri")
            self._diag_scroll.setVisible(False)
        else:
            # Iki kanal: ana, referans, oran + order karsilastirma + tani karti
            self._plot_tabs.addTab(self._main_wf_tab,  "🌊  Waterfall (Ana)")
            self._plot_tabs.addTab(self._ref_wf_tab,   "🌊  Waterfall (Referans)")
            self._plot_tabs.addTab(self._ratio_wf_tab, "📐  Waterfall Orani (dB)")
            self._plot_tabs.addTab(self._canvas_orders,"📈  Order Karsilastirma")
            self._plot_tabs.addTab(self._canvas_card,  "📋  Tani Karti")
            self._diag_scroll.setVisible(True)

    # ── Motor & kanal combo'lari guncel tut ───────────────────────────────
    @staticmethod
    def _mklabel(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _refresh_combos(self, *_args):
        """Store icerigi degisince tum motor + kanal combo'lari guncellenir.

        Analiz akisi waterfall/order tipi kanallar uzerinde calistigi icin
        FFT Max Hold kanallari combobox'larda gosterilmez (waterfall isleme
        akisi degisiklik yapilmadan korunur).
        """
        engines = sorted({
            r.engine_id for _, r in self._store.items()
            if r.data_type != DataType.FFT_MAX_HOLD
        })
        for combo in (self._single_motor, self._ref_motor, self._main_motor):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(engines)
            if cur in engines:
                combo.setCurrentText(cur)
            combo.blockSignals(False)

        self._refresh_channel_combo(self._single_motor, self._single_combo)
        self._refresh_channel_combo(self._ref_motor,    self._ref_combo)
        self._refresh_channel_combo(self._main_motor,   self._main_combo)

    def _refresh_channel_combo(self, motor_combo: QComboBox,
                               channel_combo: QComboBox):
        motor = motor_combo.currentText()
        keys = [
            k for k, r in self._store.items()
            if r.engine_id == motor and r.data_type != DataType.FFT_MAX_HOLD
        ]
        cur = channel_combo.currentText()
        channel_combo.blockSignals(True)
        channel_combo.clear()
        channel_combo.addItems(keys)
        if cur in keys:
            channel_combo.setCurrentText(cur)
        channel_combo.blockSignals(False)

    def _on_single_motor_changed(self, _text: str):
        self._refresh_channel_combo(self._single_motor, self._single_combo)

    def _on_ref_motor_changed(self, _text: str):
        self._refresh_channel_combo(self._ref_motor, self._ref_combo)

    def _on_main_motor_changed(self, _text: str):
        self._refresh_channel_combo(self._main_motor, self._main_combo)

    # ── Tek kanal goruntuleme ─────────────────────────────────────────────
    def _run_single(self):
        key = self._single_combo.currentText()
        run = self._store.get(key) if key else None
        if run is None:
            QMessageBox.warning(self, "Eksik giris",
                                "Lutfen once Veri Yonetimi'nden bir kanal yukleyin.")
            return

        self._worker = SingleChannelWorker(run)
        self._worker.progress.connect(lambda m: self.log_message.emit(m, "INFO"))
        self._worker.finished.connect(self._on_single_done)
        self._worker.error.connect(self._on_worker_error)

        self._single_run_btn.setEnabled(False)
        self._overlay.show_loading("Goruntuleniyor...", key)
        self._worker.start()

    def _on_single_done(self, order_data, run):
        self._overlay.hide_loading()
        self._single_run_btn.setEnabled(True)
        self._render_single(run, order_data)
        self.log_message.emit(f"✓ {run.engine_id} kanal goruntulendi", "SUCCESS")

    def _render_single(self, run, order_data):
        import matplotlib
        matplotlib.use("Agg")
        from plots import plot_order_comparison

        # Mevcut run'i kaydet — kontrol cubugu yenilemeleri bunu kullanir
        self._cur_single_run = run
        self._cur_meas_run = None
        self._cur_ref_run = None

        # Waterfall sekmesi: kontrol cubugundaki RPM placeholder'larini guncelle
        # ve varsayilan araliklarla cizdir.
        self._main_wf_tab.set_rpm_range(*run.rpm_range)
        self._main_wf_tab.render()

        # Tek kanal: order genlikleri (referans yok → karsilastirma yapilmaz)
        try:
            empty_ref = {}
            fig_ord = plot_order_comparison(order_data, empty_ref, anomalies=[])
            self._canvas_orders.set_figure(fig_ord)
        except Exception as exc:
            logger.warning("Order plot hatasi: %s", exc)

    # ── Iki kanal karsilastirma ───────────────────────────────────────────
    def _run_compare(self):
        ref_key  = self._ref_combo.currentText()
        meas_key = self._main_combo.currentText()
        ref_run  = self._store.get(ref_key)  if ref_key  else None
        meas_run = self._store.get(meas_key) if meas_key else None

        if ref_run is None or meas_run is None:
            QMessageBox.warning(self, "Eksik giris",
                                "Karsilastirma icin iki kanal secmelisiniz.")
            return
        if ref_key == meas_key:
            QMessageBox.warning(self, "Gecersiz secim",
                                "Referans ve ana kanal ayni olamaz.")
            return

        # is_reference bayragini referans olarak kullanilana isaretle
        ref_run.is_reference = True

        self._worker = CompareChannelsWorker(meas_run, ref_run)
        self._worker.progress.connect(lambda m: self.log_message.emit(m, "INFO"))
        self._worker.finished.connect(self._on_compare_done)
        self._worker.error.connect(self._on_worker_error)

        self._compare_run_btn.setEnabled(False)
        self._overlay.show_loading("Karsilastirma calistiriliyor...", meas_key)
        self._worker.start()

    def _on_compare_done(self, report, order_data, ref_order_data, meas_run, ref_run):
        self._overlay.hide_loading()
        self._compare_run_btn.setEnabled(True)
        self._render_compare(report, order_data, ref_order_data, meas_run, ref_run)
        self.log_message.emit(
            f"✓ Karsilastirma tamam — Skor {report.overall_health_score:.0f}/100 "
            f"· {len(report.anomalies)} anomali",
            "SUCCESS",
        )

    def _render_compare(self, report, order_data, ref_order_data, meas_run, ref_run):
        import matplotlib
        matplotlib.use("Agg")
        from plots import plot_order_comparison, plot_diagnostic_card

        # Mevcut run'lari kaydet
        self._cur_single_run = None
        self._cur_meas_run = meas_run
        self._cur_ref_run  = ref_run

        # Uc waterfall sekmesini render et — kontrol cubuklari _render_*_wf
        # fonksiyonlarini yeniden tetikleyebilir.
        self._main_wf_tab.set_rpm_range(*meas_run.rpm_range)
        self._main_wf_tab.render()
        self._ref_wf_tab.set_rpm_range(*ref_run.rpm_range)
        self._ref_wf_tab.render()
        self._ratio_wf_tab.set_rpm_range(*meas_run.rpm_range)
        self._ratio_wf_tab.render()

        try:
            fig_ord = plot_order_comparison(order_data, ref_order_data,
                                            report.anomalies)
            self._canvas_orders.set_figure(fig_ord)
        except Exception as exc:
            logger.warning("Order karsilastirma hatasi: %s", exc)

        try:
            fig_card = plot_diagnostic_card(report)
            self._canvas_card.set_figure(fig_card)
        except Exception as exc:
            logger.warning("Tani karti hatasi: %s", exc)

        self._diag_widget.set_report(report)

    def _on_worker_error(self, msg: str):
        self._overlay.hide_loading()
        self._single_run_btn.setEnabled(True)
        self._compare_run_btn.setEnabled(True)
        self.log_message.emit(f"✕ Hata: {msg.splitlines()[0]}", "ERROR")
        QMessageBox.critical(self, "Hata", msg[:400])

    # ── Waterfall render callback'leri (kontrol cubuklarindan cagrilir) ────
    def _render_main_wf(self, freq_min, freq_max, rpm_min, rpm_max):
        run = self._cur_single_run or self._cur_meas_run
        if run is None:
            return None
        from plots import plot_waterfall
        return plot_waterfall(
            run,
            freq_min=freq_min if freq_min is not None else 0.0,
            freq_max=freq_max if freq_max is not None else 3000.0,
            rpm_min=rpm_min, rpm_max=rpm_max,
        )

    def _render_ref_wf(self, freq_min, freq_max, rpm_min, rpm_max):
        if self._cur_ref_run is None:
            return None
        from plots import plot_waterfall
        return plot_waterfall(
            self._cur_ref_run,
            freq_min=freq_min if freq_min is not None else 0.0,
            freq_max=freq_max if freq_max is not None else 3000.0,
            rpm_min=rpm_min, rpm_max=rpm_max,
        )

    def _render_ratio_wf(self, freq_min, freq_max, rpm_min, rpm_max):
        if self._cur_meas_run is None or self._cur_ref_run is None:
            return None
        from plots import plot_waterfall_ratio
        return plot_waterfall_ratio(
            self._cur_meas_run, self._cur_ref_run,
            freq_min=freq_min if freq_min is not None else 0.0,
            freq_max=freq_max if freq_max is not None else 3000.0,
            rpm_min=rpm_min, rpm_max=rpm_max,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNOSIS PANEL  (Analiz sayfasinin sag tarafi)
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosisPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(16)

        # Saglik skoru + ozet
        score_card, score_body = _card("Saglik Skoru")
        score_row = QHBoxLayout()
        self._dial = HealthScoreDial(100)
        score_row.addWidget(self._dial)
        summary_col = QVBoxLayout()
        self._summary_label = QLabel("Analiz bekleniyor...")
        self._summary_label.setWordWrap(True)
        self._summary_label.setObjectName("fieldLabel")
        summary_col.addWidget(self._summary_label)
        self._engine_id_label = QLabel("")
        self._engine_id_label.setObjectName("pageTitle")
        summary_col.addWidget(self._engine_id_label)
        score_row.addLayout(summary_col, stretch=1)
        score_body.addLayout(score_row)
        layout.addWidget(score_card)

        # Teshis tablosu
        fault_card, fault_body = _card("Teshis Edilen Arizalar")
        self._fault_table = _make_table(["Ariza", "Kategori", "Guven", "Severity"])
        self._fault_table.setMinimumHeight(140)
        self._fault_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._fault_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._fault_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._fault_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        fault_body.addWidget(self._fault_table)
        layout.addWidget(fault_card)

        # Anomali tablosu
        anom_card, anom_body = _card("Anomali Listesi")
        self._anom_table = _make_table(["Order", "RPM", "Frekans", "Oran", "Severity"])
        self._anom_table.setMinimumHeight(140)
        anom_body.addWidget(self._anom_table)
        layout.addWidget(anom_card)

        # Oneriler
        rec_card, rec_body = _card("Oneriler")
        self._rec_text = QTextEdit()
        self._rec_text.setReadOnly(True)
        self._rec_text.setObjectName("logPanel")
        self._rec_text.setMinimumHeight(120)
        rec_body.addWidget(self._rec_text)
        layout.addWidget(rec_card)

    def set_report(self, report) -> None:
        self._dial.set_score(report.overall_health_score)
        self._engine_id_label.setText(report.engine_id)
        self._summary_label.setText(report.summary)

        self._fault_table.setRowCount(0)
        for d in report.fault_diagnoses:
            row = self._fault_table.rowCount()
            self._fault_table.insertRow(row)
            color = _severity_color(d["severity"])
            self._fault_table.setItem(row, 0, _table_item(d["fault_name"]))
            self._fault_table.setItem(row, 1, _table_item(d["category"]))
            self._fault_table.setItem(row, 2, _table_item(f"{int(d['confidence']*100)}%"))
            self._fault_table.setItem(row, 3, _table_item(d["severity"], color, bold=True))

        self._anom_table.setRowCount(0)
        for a in sorted(report.anomalies, key=lambda x: -x.amplitude_ratio):
            row = self._anom_table.rowCount()
            self._anom_table.insertRow(row)
            color = _severity_color(a.severity)
            self._anom_table.setItem(row, 0, _table_item(f"{a.order:.1f}×"))
            self._anom_table.setItem(row, 1, _table_item(f"{a.rpm:.0f}"))
            self._anom_table.setItem(row, 2, _table_item(f"{a.frequency_hz:.1f} Hz"))
            self._anom_table.setItem(row, 3, _table_item(f"×{a.amplitude_ratio:.2f}", color, bold=True))
            self._anom_table.setItem(row, 4, _table_item(a.severity, color))

        recs = "\n\n".join(f"→ {r}" for r in report.recommendations) \
            or "Anormallik tespit edilmedi."
        self._rec_text.setPlainText(recs)


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: ENGINE CONFIG VIEWER
# ─────────────────────────────────────────────────────────────────────────────

class PageEngineConfig(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        outer.setSpacing(8)

        tabs = QTabWidget()
        outer.addWidget(tabs, stretch=1)

        # Tab 1: Order Tanimlari
        order_widget = QWidget()
        ol = QVBoxLayout(order_widget)
        ol.setContentsMargins(12, 12, 12, 12)
        order_tbl = _make_table(["Order", "İsim", "Kaynak", "Aciklama", "Ariza Gostergeleri"])
        order_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        order_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        order_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        order_tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        order_tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        from engine_config import ORDER_DEFINITIONS
        _CAT_COLORS = {
            "Gear": "#3fb950",
            "Combustion": "#e8724a",
            "Imbalance": "#58a6ff",
            "Valve Train": "#f78166",
            "Structural Resonance": "#8b949e",
            "Mechanical": "#f0883e",
            "Bearing": "#bc8cff",
            "Misalignment": "#d29922",
            "Propeller": "#bc8cff",
            "Engine Mount": "#d29922",
        }
        for order, odef in sorted(ORDER_DEFINITIONS.items()):
            row = order_tbl.rowCount()
            order_tbl.insertRow(row)
            cat_color = _CAT_COLORS.get(odef.category.value, "#8b949e")
            order_tbl.setItem(row, 0, _table_item(f"{order}×", "#58a6ff", bold=True))
            order_tbl.setItem(row, 1, _table_item(odef.name))
            order_tbl.setItem(row, 2, _table_item(odef.source, cat_color))
            order_tbl.setItem(row, 3, _table_item(odef.description[:80]))
            order_tbl.setItem(row, 4, _table_item(", ".join(odef.fault_indicators[:3])))

        ol.addWidget(order_tbl)
        tabs.addTab(order_widget, "Order Tanimlari")

        # Tab 2: Ariza Imzalari
        fault_widget = QWidget()
        fl = QVBoxLayout(fault_widget)
        fl.setContentsMargins(12, 12, 12, 12)
        fault_tbl = _make_table(["Ariza", "Kategori", "Birincil Orders", "İkincil Orders", "Esik (×)"])
        fault_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        from engine_config import FAULT_SIGNATURES
        for sig in FAULT_SIGNATURES:
            row = fault_tbl.rowCount()
            fault_tbl.insertRow(row)
            fault_tbl.setItem(row, 0, _table_item(sig.name, bold=True))
            fault_tbl.setItem(row, 1, _table_item(sig.category.value))
            fault_tbl.setItem(row, 2, _table_item(", ".join(f"{o}×" for o in sig.primary_orders), "#58a6ff"))
            fault_tbl.setItem(row, 3, _table_item(", ".join(f"{o}×" for o in sig.secondary_orders)))
            fault_tbl.setItem(row, 4, _table_item(f"×{sig.amplitude_ratio_threshold}"))

        fl.addWidget(fault_tbl)
        tabs.addTab(fault_widget, "Ariza Imzalari")

        # Tab 3: Motor Parametreleri
        param_widget = QWidget()
        pl = QVBoxLayout(param_widget)
        pl.setContentsMargins(12, 12, 12, 12)

        from engine_config import ENGINE_CONFIG
        param_tbl = _make_table(["Parametre", "Deger"])
        param_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        param_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        for key, val in ENGINE_CONFIG.items():
            row = param_tbl.rowCount()
            param_tbl.insertRow(row)
            param_tbl.setItem(row, 0, _table_item(str(key), "#8b949e"))
            param_tbl.setItem(row, 1, _table_item(str(val)))

        pl.addWidget(param_tbl)
        tabs.addTab(param_widget, "Motor Parametreleri")


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: LOG  (genel uygulama logu)
# ─────────────────────────────────────────────────────────────────────────────

class PageLog(QWidget):
    """Tum sayfalardan gelen log mesajlarini gosteren basit sayfa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        outer.setSpacing(8)

        log_card, log_body = _card("Uygulama Gunlugu")
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self._clear_btn = QPushButton("🗑  Temizle")
        self._clear_btn.setObjectName("btnBrowse")
        toolbar.addWidget(self._clear_btn)
        log_body.addLayout(toolbar)

        self._log = LogPanel()
        self._log.setMinimumHeight(400)
        log_body.addWidget(self._log, stretch=1)
        outer.addWidget(log_card, stretch=1)

        self._clear_btn.clicked.connect(self._log.clear)

    def append(self, msg: str, level: str = "INFO") -> None:
        self._log.append_log(msg, level)
