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

from ui_worker import LoadChannelWorker, CompareChannelsWorker, SingleChannelWorker
from ui_widgets import (
    HealthScoreDial, FilePickerRow,
    LoadingOverlay, LogPanel, MatplotlibCanvas, ChannelStore,
)

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
    """Veri yukleme ve yuklenmis kanallari yonetme sayfasi."""

    log_message = Signal(str, str)   # (msg, level)

    def __init__(self, store: ChannelStore, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._store = store
        self._worker: Optional[LoadChannelWorker] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        outer.setSpacing(12)

        # Iki sutunlu yerlesim — sol: yukleme kart, sag: kanal listesi
        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, stretch=1)

        # ── Sol: Veri yukleme kart ────────────────────────────────────────
        left_wrap = QVBoxLayout()
        left_wrap.setSpacing(14)
        cols.addLayout(left_wrap, stretch=0)

        upload_card, upload_body = _card("⬆️  Veri Yukle")
        self._picker = FilePickerRow("Veri dosyasi:")
        upload_body.addWidget(self._picker)

        eng_edit = QLineEdit()
        eng_edit.setPlaceholderText("ENG-042")
        self._engine_id = eng_edit
        upload_body.addLayout(_field_row("Motor ID:", eng_edit))

        run_edit = QLineEdit()
        run_edit.setPlaceholderText("RUN-001")
        run_edit.setText("RUN-001")
        self._run_id = run_edit
        upload_body.addLayout(_field_row("Run ID:", run_edit))

        from engine_config import LOCATION_CODES, LOCATION_NAMES
        sensor_combo = QComboBox()
        for code in LOCATION_CODES:
            sensor_combo.addItem(f"{code}  —  {LOCATION_NAMES[code]}", code)
        self._sensor_combo = sensor_combo
        upload_body.addLayout(_field_row("Sensor lokasyonu:", sensor_combo))

        axis_combo = QComboBox()
        axis_combo.addItems(["X", "Y", "Z"])
        self._axis_combo = axis_combo
        upload_body.addLayout(_field_row("Eksen:", axis_combo))

        self._load_btn = QPushButton("➕  Kanali Yukle")
        self._load_btn.setObjectName("btnPrimary")
        self._load_btn.setFixedHeight(40)
        self._load_btn.clicked.connect(self._load_channel)
        upload_body.addWidget(self._load_btn)

        # auto-fill from filename if possible
        self._picker.file_selected.connect(self._on_file_selected)

        left_wrap.addWidget(upload_card)
        left_wrap.addStretch()
        # Sabit genislik — sag tarafa yer birak
        upload_card.setFixedWidth(420)

        # ── Sag: Yuklenmis kanallar listesi ───────────────────────────────
        right_wrap = QVBoxLayout()
        right_wrap.setSpacing(14)
        cols.addLayout(right_wrap, stretch=1)

        list_card, list_body = _card("🗂️  Yuklenmis Kanallar")

        # Filtre satiri
        filter_row = QHBoxLayout()
        flt_lbl = QLabel("🔎  Filtrele:")
        flt_lbl.setObjectName("fieldLabel")
        filter_row.addWidget(flt_lbl)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Motor ID, lokasyon veya eksene gore ara...")
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_edit, stretch=1)
        self._count_label = QLabel("0 kanal")
        self._count_label.setObjectName("fieldLabel")
        filter_row.addWidget(self._count_label)
        list_body.addLayout(filter_row)

        # Kanal tablosu
        self._channel_table = _make_table([
            "Kanal", "Motor ID", "Lokasyon", "Eksen",
            "Run ID", "RPM Aralıgi", "Slice", "İslem",
        ])
        hdr = self._channel_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        list_body.addWidget(self._channel_table, stretch=1)

        right_wrap.addWidget(list_card, stretch=1)

        # Store sinyallerine baglan
        self._store.channel_added.connect(self._on_channel_added)
        self._store.channel_removed.connect(self._on_channel_removed)

        # key -> row index haritasi (dinamik olarak yeniden olusturulur)
        self._row_keys: list[str] = []

        self._overlay = LoadingOverlay(self)

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Dosya secimi sonrasi alan doldurma ────────────────────────────────
    def _on_file_selected(self, path: str):
        from importers import parse_filename
        parsed = parse_filename(Path(path))
        if not parsed:
            return
        self._engine_id.setText(parsed["engine_id"])
        self._run_id.setText(parsed["run_id"])
        # Lokasyonu combo'da bul
        loc = parsed["location"]
        for i in range(self._sensor_combo.count()):
            if self._sensor_combo.itemData(i) == loc:
                self._sensor_combo.setCurrentIndex(i)
                break
        # Ekseni combo'da bul
        ax = parsed["axis"]
        idx_a = self._axis_combo.findText(ax)
        if idx_a >= 0:
            self._axis_combo.setCurrentIndex(idx_a)

    def _load_channel(self):
        if not self._picker.path():
            QMessageBox.warning(self, "Eksik giris", "Lutfen veri dosyasi secin.")
            return
        if not self._engine_id.text().strip():
            QMessageBox.warning(self, "Eksik giris", "Motor ID giriniz.")
            return

        loc_code = self._sensor_combo.currentData() or self._sensor_combo.currentText().split()[0]
        self._worker = LoadChannelWorker(
            path            = self._picker.path(),
            engine_id       = self._engine_id.text().strip(),
            run_id          = self._run_id.text().strip() or "RUN-001",
            sensor_location = loc_code,
            axis            = self._axis_combo.currentText(),
        )
        self._worker.progress.connect(lambda m: self.log_message.emit(m, "INFO"))
        self._worker.finished.connect(self._on_load_done)
        self._worker.error.connect(self._on_load_error)

        self._load_btn.setEnabled(False)
        self._overlay.show_loading("Kanal yukleniyor...",
                                   Path(self._picker.path()).name)
        self._worker.start()

    def _on_load_done(self, run):
        self._overlay.hide_loading()
        self._load_btn.setEnabled(True)
        key = self._store.add(run)
        self.log_message.emit(f"✓ Kanal eklendi: {key}", "SUCCESS")

    def _on_load_error(self, msg: str):
        self._overlay.hide_loading()
        self._load_btn.setEnabled(True)
        self.log_message.emit(f"✕ Yukleme hatasi: {msg.splitlines()[0]}", "ERROR")
        QMessageBox.critical(self, "Yukleme Hatasi", msg[:400])

    # ── Tablo yonetimi ────────────────────────────────────────────────────
    def _on_channel_added(self, key: str, run):
        self._rebuild_table()

    def _on_channel_removed(self, key: str):
        self._rebuild_table()

    def _rebuild_table(self):
        self._channel_table.setRowCount(0)
        self._row_keys.clear()
        query = self._filter_edit.text().strip().lower()

        for key, run in self._store.items():
            if query and query not in key.lower():
                continue
            row = self._channel_table.rowCount()
            self._channel_table.insertRow(row)
            self._row_keys.append(key)

            rpm_lo, rpm_hi = run.rpm_range
            self._channel_table.setItem(row, 0, _table_item(key, "#e6edf3"))
            self._channel_table.setItem(row, 1, _table_item(run.engine_id, "#58a6ff", bold=True))
            self._channel_table.setItem(row, 2, _table_item(run.sensor_location))
            self._channel_table.setItem(row, 3, _table_item(run.axis))
            self._channel_table.setItem(row, 4, _table_item(run.run_id))
            self._channel_table.setItem(row, 5, _table_item(f"{rpm_lo:.0f}–{rpm_hi:.0f}"))
            self._channel_table.setItem(row, 6, _table_item(str(run.n_slices)))

            btn = QPushButton("🗑  Kaldir")
            btn.setObjectName("btnBrowse")
            btn.clicked.connect(lambda _checked=False, k=key: self._store.remove(k))
            self._channel_table.setCellWidget(row, 7, btn)

        self._count_label.setText(f"{self._channel_table.rowCount()} kanal")

    def _apply_filter(self, _text: str):
        self._rebuild_table()


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

        # Motor combo (her iki modda ortak — kanallari filtreler)
        lbl_motor = QLabel("Motor:")
        lbl_motor.setObjectName("fieldLabel")
        top_row.addWidget(lbl_motor)
        self._motor_combo = QComboBox()
        self._motor_combo.setMinimumWidth(140)
        self._motor_combo.setMaximumWidth(180)
        self._motor_combo.currentTextChanged.connect(self._on_motor_changed)
        top_row.addWidget(self._motor_combo)

        # Kanal seciciler — modlara gore birden fazla
        self._selector_stack = QStackedWidget()
        top_row.addWidget(self._selector_stack, stretch=1)

        # Tek kanal seciciyi sar
        single_wrap = QWidget()
        sw_l = QHBoxLayout(single_wrap)
        sw_l.setContentsMargins(0, 0, 0, 0)
        sw_l.setSpacing(8)
        lbl_s = QLabel("Kanal:")
        lbl_s.setObjectName("fieldLabel")
        sw_l.addWidget(lbl_s)
        self._single_combo = QComboBox()
        self._single_combo.setMinimumWidth(220)
        self._single_combo.setMaximumWidth(320)
        sw_l.addWidget(self._single_combo)
        sw_l.addStretch()
        self._selector_stack.addWidget(single_wrap)

        # Iki kanal secicileri sar (yan yana)
        compare_wrap = QWidget()
        cw_l = QHBoxLayout(compare_wrap)
        cw_l.setContentsMargins(0, 0, 0, 0)
        cw_l.setSpacing(8)
        lbl_r = QLabel("Referans:")
        lbl_r.setObjectName("fieldLabel")
        cw_l.addWidget(lbl_r)
        self._ref_combo = QComboBox()
        self._ref_combo.setMinimumWidth(200)
        self._ref_combo.setMaximumWidth(280)
        cw_l.addWidget(self._ref_combo)
        lbl_m = QLabel("Ana:")
        lbl_m.setObjectName("fieldLabel")
        cw_l.addWidget(lbl_m)
        self._main_combo = QComboBox()
        self._main_combo.setMinimumWidth(200)
        self._main_combo.setMaximumWidth(280)
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

        # Plot canvas'lari — modlar arasinda paylasilir, set_figure ile guncellenir
        self._canvas_main_wf  = MatplotlibCanvas()  # Tek kanal & ana kanal waterfall
        self._canvas_ref_wf   = MatplotlibCanvas()  # Karsilastirmada referans waterfall
        self._canvas_ratio_wf = MatplotlibCanvas()  # Karsilastirmada oran waterfall
        self._canvas_orders   = MatplotlibCanvas()
        self._canvas_card     = MatplotlibCanvas()

        # Tab indeksleri runtime'da yeniden duzenlenir
        self._plot_tabs.addTab(self._canvas_main_wf,  "🌊  Waterfall")
        self._plot_tabs.addTab(self._canvas_orders,   "📊  Order Genlikleri")

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
            self._plot_tabs.addTab(self._canvas_main_wf, "🌊  Waterfall")
            self._plot_tabs.addTab(self._canvas_orders,  "📊  Order Genlikleri")
            self._diag_scroll.setVisible(False)
        else:
            # Iki kanal: ana, referans, oran + order karsilastirma + tani karti
            self._plot_tabs.addTab(self._canvas_main_wf,  "🌊  Waterfall (Ana)")
            self._plot_tabs.addTab(self._canvas_ref_wf,   "🌊  Waterfall (Referans)")
            self._plot_tabs.addTab(self._canvas_ratio_wf, "📐  Waterfall Orani (dB)")
            self._plot_tabs.addTab(self._canvas_orders,   "📈  Order Karsilastirma")
            self._plot_tabs.addTab(self._canvas_card,     "📋  Tani Karti")
            self._diag_scroll.setVisible(True)

    # ── Motor & kanal combo'lari guncel tut ───────────────────────────────
    def _refresh_combos(self, *_args):
        # Motor listesi — store'daki tum kanallardan distinct engine_id
        engines = sorted({r.engine_id for _, r in self._store.items()})
        cur_motor = self._motor_combo.currentText()
        self._motor_combo.blockSignals(True)
        self._motor_combo.clear()
        self._motor_combo.addItems(engines)
        if cur_motor in engines:
            self._motor_combo.setCurrentText(cur_motor)
        self._motor_combo.blockSignals(False)

        # Bunlar motor seciminden filtrelenir
        self._refresh_channel_combos()

    def _on_motor_changed(self, _text: str):
        self._refresh_channel_combos()

    def _refresh_channel_combos(self):
        motor = self._motor_combo.currentText()
        keys = [k for k, r in self._store.items() if r.engine_id == motor]
        for combo in (self._single_combo, self._ref_combo, self._main_combo):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(keys)
            if cur in keys:
                combo.setCurrentText(cur)
            combo.blockSignals(False)

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
        from plots import plot_waterfall, plot_order_comparison

        try:
            fig = plot_waterfall(run)
            self._canvas_main_wf.set_figure(fig)
        except Exception as exc:
            logger.warning("Waterfall plot hatasi: %s", exc)

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
        from plots import (plot_waterfall, plot_waterfall_ratio,
                           plot_order_comparison, plot_diagnostic_card)

        try:
            fig_main = plot_waterfall(meas_run)
            self._canvas_main_wf.set_figure(fig_main)
        except Exception as exc:
            logger.warning("Ana waterfall hatasi: %s", exc)

        try:
            fig_ref = plot_waterfall(ref_run)
            self._canvas_ref_wf.set_figure(fig_ref)
        except Exception as exc:
            logger.warning("Ref waterfall hatasi: %s", exc)

        try:
            fig_ratio = plot_waterfall_ratio(meas_run, ref_run)
            self._canvas_ratio_wf.set_figure(fig_ratio)
        except Exception as exc:
            logger.warning("Oran waterfall hatasi: %s", exc)

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
