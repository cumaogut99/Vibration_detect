"""
ui_pages.py — Tüm sayfa widget'ları.

Sayfalar:
  PageDataIngest      — CSV -> DuckDB veri yükleme
  PageSingleAnalysis  — Tek motor analizi (eski; dosya picker)
  PageFleetAnalysis   — Filo analizi (eski; dosya picker)
  PageDemoRun         — Demo / sentetik veri
  PageResults         — Sonuç görüntüleyici (waterfall + order + diagnose)
  PageEngineConfig    — Engine config'i göster/açıkla
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QComboBox, QLineEdit, QHeaderView,
    QSizePolicy, QMessageBox, QTextEdit, QCheckBox, QDateEdit,
    QCompleter,
)
from PySide6.QtCore import Qt, Signal, QTimer, QDate
from PySide6.QtGui import QColor, QFont

from ui_worker import (
    DemoWorker, DataIngestWorker,
    DbAnalysisWorker, DbFleetAnalysisWorker,
)
from ui_widgets import (
    SectionTitle, Divider, StatusBadge, HealthScoreDial,
    EngineCard, FilePickerRow,
    LoadingOverlay, LogPanel, MatplotlibCanvas, WaterfallControlBar,
)
from db_layer import DataStore

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _page_header(title: str, subtitle: str) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    layout.addWidget(t)
    s = QLabel(subtitle)
    s.setObjectName("pageSubtitle")
    layout.addWidget(s)
    return w


def _card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Returns (card frame, body layout)."""
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
#  PAGE: DATA INGEST  (CSV → DuckDB)
# ─────────────────────────────────────────────────────────────────────────────

class PageDataIngest(QWidget):
    """
    CSV / NPZ / TXT dosyalarını seçip motor / kanal / referans
    metadata'sıyla birlikte DuckDB'ye yazan sayfa.

    ``runs_changed`` sinyali tablo güncellendiğinde fırlatılır; diğer
    DB-tabanlı sayfalar bu sinyale bağlanarak kendi listelerini
    tazeleyebilir.
    """

    runs_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._worker: Optional[DataIngestWorker] = None
        self._store: Optional[DataStore] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        outer.addWidget(_page_header(
            "📥  Veri Yükle",
            "CSV/NPZ/TXT dosyalarını veritabanına aktarın. "
            "Dosya adından otomatik motor / lokasyon / eksen çıkarımı yapılır.",
        ))
        outer.addWidget(Divider())

        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, stretch=1)

        # ── Sol: form ─────────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(14)
        cols.addLayout(left, stretch=0)

        # Dosya seçme kartı
        file_card, file_body = _card("📂  Veri Dosyası")
        self._picker = FilePickerRow("Dosya:")
        self._picker.file_selected.connect(self._on_file_selected)
        file_body.addWidget(self._picker)
        autofill_btn = QPushButton("Dosya adından alanları doldur")
        autofill_btn.setObjectName("btnBrowse")
        autofill_btn.clicked.connect(self._autofill_from_filename)
        file_body.addWidget(autofill_btn)
        left.addWidget(file_card)

        # Metadata kartı
        meta_card, meta_body = _card("🏷️  Metadata")

        self._engine_id = QLineEdit()
        self._engine_id.setPlaceholderText("ENG-042")
        # Autocomplete daha sonra populate edilir
        self._engine_completer = QCompleter([], self)
        self._engine_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._engine_id.setCompleter(self._engine_completer)
        meta_body.addLayout(_field_row("Motor ID:", self._engine_id))

        from engine_config import LOCATION_CODES, LOCATION_NAMES
        self._location = QComboBox()
        for code in LOCATION_CODES:
            self._location.addItem(f"{code}  —  {LOCATION_NAMES[code]}", code)
        meta_body.addLayout(_field_row("Lokasyon:", self._location))

        self._axis = QComboBox()
        self._axis.addItems(["X", "Y", "Z"])
        meta_body.addLayout(_field_row("Eksen:", self._axis))

        self._run_id = QLineEdit()
        self._run_id.setPlaceholderText("RUN-001")
        meta_body.addLayout(_field_row("Run ID:", self._run_id))

        self._date = QDateEdit()
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setCalendarPopup(True)
        self._date.setDate(QDate.currentDate())
        meta_body.addLayout(_field_row("Ölçüm tarihi:", self._date))

        self._is_ref = QCheckBox("Bu kanal için referans olarak işaretle")
        meta_body.addWidget(self._is_ref)

        left.addWidget(meta_card)

        # Çalıştır butonu
        self._save_btn = QPushButton("💾  Veritabanına Yaz")
        self._save_btn.setObjectName("btnPrimary")
        self._save_btn.setFixedHeight(42)
        self._save_btn.clicked.connect(self._save_to_db)
        left.addWidget(self._save_btn)

        # DB konum bilgisi
        path_lbl = QLabel("")
        path_lbl.setObjectName("fieldLabel")
        path_lbl.setWordWrap(True)
        self._path_lbl = path_lbl
        left.addWidget(path_lbl)

        left.addStretch()

        # ── Sağ: son eklenenler tablosu + log ────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(12)
        cols.addLayout(right, stretch=1)

        recent_card, recent_body = _card("🗂️  Son Eklenen Run'lar")
        self._recent_table = _make_table(
            ["ID", "Motor", "Lokasyon", "Eksen", "Run", "Tarih", "Ref", "Slice"]
        )
        self._recent_table.setMinimumHeight(280)
        recent_body.addWidget(self._recent_table)
        right.addWidget(recent_card, stretch=1)

        log_card, log_body = _card("📋  İşlem Günlüğü")
        self._log = LogPanel()
        self._log.setMaximumHeight(140)
        log_body.addWidget(self._log)
        right.addWidget(log_card)

        self._overlay = LoadingOverlay(self)

        # DB'yi aç + tabloyu doldur
        QTimer.singleShot(0, self._init_store)

    # ── Yaşam döngüsü ─────────────────────────────────────────────────────

    def _init_store(self) -> None:
        try:
            self._store = DataStore()
            self._path_lbl.setText(f"DB: {self._store.db_path}")
            self._refresh_recent()
            self._refresh_engine_completer()
        except Exception as exc:
            logger.error("DataStore acilamadi: %s", exc)
            QMessageBox.critical(
                self, "Veritabanı Hatası",
                f"DataStore açılamadı:\n{exc}",
            )

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Dosya → form ──────────────────────────────────────────────────────

    def _on_file_selected(self, path: str) -> None:
        # Default run_id = stem of file if user hasn't typed anything yet
        if not self._run_id.text().strip():
            self._run_id.setText(Path(path).stem[:32])
        # Try auto-parse silently
        self._autofill_from_filename(silent=True)

    def _autofill_from_filename(self, silent: bool = False) -> None:
        from importers import parse_filename
        path = self._picker.path()
        if not path:
            if not silent:
                QMessageBox.information(
                    self, "Dosya yok", "Önce bir veri dosyası seçin."
                )
            return
        parsed = parse_filename(Path(path))
        if not parsed:
            if not silent:
                QMessageBox.information(
                    self, "Parse edilemedi",
                    "Dosya adı standart formatla eşleşmedi:\n"
                    "  ENGINE-ID__YYYYMMDD__LOCATION__AXIS__RUN-ID.csv",
                )
            return

        self._engine_id.setText(parsed["engine_id"])
        self._run_id.setText(parsed["run_id"])
        # Lokasyon combobox
        loc = parsed["location"]
        idx = self._location.findData(loc)
        if idx >= 0:
            self._location.setCurrentIndex(idx)
        # Eksen
        axis_idx = self._axis.findText(parsed["axis"])
        if axis_idx >= 0:
            self._axis.setCurrentIndex(axis_idx)
        # Tarih
        d = parsed.get("date") or ""
        if len(d) == 8 and d.isdigit():
            self._date.setDate(QDate(int(d[:4]), int(d[4:6]), int(d[6:8])))

        self._log.append_log(
            f"Dosya adından çıkarıldı: {parsed['engine_id']} "
            f"/ {loc}{parsed['axis']} / {parsed['run_id']}",
            "INFO",
        )

    # ── Kaydetme ──────────────────────────────────────────────────────────

    def _save_to_db(self) -> None:
        path = self._picker.path()
        if not path:
            QMessageBox.warning(self, "Eksik giriş", "Lütfen bir veri dosyası seçin.")
            return
        engine_id = self._engine_id.text().strip()
        if not engine_id:
            QMessageBox.warning(self, "Eksik giriş", "Motor ID boş olamaz.")
            return
        run_id = self._run_id.text().strip() or "RUN-001"
        location = self._location.currentData() or self._location.currentText().split()[0]
        axis = self._axis.currentText()
        is_ref = self._is_ref.isChecked()
        meas_date = self._date.date().toPython()

        self._worker = DataIngestWorker(
            file_path=path,
            engine_id=engine_id,
            run_id=run_id,
            sensor_location=location,
            axis=axis,
            is_reference=is_ref,
            measurement_date=meas_date,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._save_btn.setEnabled(False)
        self._overlay.show_loading("Veritabanına yazılıyor…", engine_id)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._log.append_log(msg, "INFO")
        self._overlay._sub.setText(msg)

    def _on_finished(self, new_id: int, engine_id: str, run_id: str) -> None:
        self._overlay.hide_loading()
        self._save_btn.setEnabled(True)
        self._log.append_log(
            f"✓ Yazıldı — id={new_id}  motor={engine_id}  run={run_id}",
            "SUCCESS",
        )
        self._refresh_recent()
        self._refresh_engine_completer()
        self.runs_changed.emit()

    def _on_error(self, msg: str) -> None:
        self._overlay.hide_loading()
        self._save_btn.setEnabled(True)
        self._log.append_log(f"✕ Hata: {msg}", "ERROR")
        QMessageBox.critical(self, "Yazma Hatası", msg[:400])

    # ── Yardımcılar ───────────────────────────────────────────────────────

    def _refresh_recent(self) -> None:
        if self._store is None:
            return
        rows = self._store.list_runs()
        self._recent_table.setRowCount(0)
        for r in rows[:50]:
            i = self._recent_table.rowCount()
            self._recent_table.insertRow(i)
            self._recent_table.setItem(i, 0, _table_item(str(r.id), "#8b949e"))
            self._recent_table.setItem(i, 1, _table_item(r.engine_id, bold=True))
            self._recent_table.setItem(i, 2, _table_item(r.sensor_location))
            self._recent_table.setItem(i, 3, _table_item(r.axis))
            self._recent_table.setItem(i, 4, _table_item(r.run_id))
            date_str = r.measurement_date.isoformat() if r.measurement_date else "—"
            self._recent_table.setItem(i, 5, _table_item(date_str))
            if r.is_reference:
                self._recent_table.setItem(i, 6, _table_item("REF", "#3fb950", bold=True))
            else:
                self._recent_table.setItem(i, 6, _table_item("—", "#8b949e"))
            self._recent_table.setItem(i, 7, _table_item(str(r.n_slices), "#8b949e"))

    def _refresh_engine_completer(self) -> None:
        if self._store is None:
            return
        from PySide6.QtCore import QStringListModel
        engines = self._store.list_engines()
        self._engine_completer.setModel(QStringListModel(engines, self._engine_completer))


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: DB-BASED SINGLE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

class PageDbSingleAnalysis(QWidget):
    """
    DuckDB tabanlı tek-motor analizi: motor + kanal seçilir, kanaldaki
    tüm run'lar listelenir, biri referans, biri ölçüm olarak işaretlenir.

    ``runs_changed`` slot'una bağlanırsa Veri Yükle sayfasında yeni
    bir run eklendiğinde liste otomatik tazelenir.
    """

    analysis_done = Signal(object, object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._worker: Optional[DbAnalysisWorker] = None
        self._store: Optional[DataStore] = None

        # Seçili id'ler
        self._sel_ref_id: Optional[int] = None
        self._sel_meas_id: Optional[int] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        outer.addWidget(_page_header(
            "🔍  Tek Motor Analizi",
            "Veritabanından bir motor + kanal seçin, ardından referans ve "
            "ölçüm run'larını işaretleyip analizi başlatın.",
        ))
        outer.addWidget(Divider())

        # ── Üst seçim çubuğu ─────────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.setSpacing(10)

        self._engine_combo = QComboBox()
        self._engine_combo.setMinimumWidth(180)
        self._engine_combo.currentTextChanged.connect(self._on_engine_changed)
        sel_row.addWidget(self._lbl("Motor:"))
        sel_row.addWidget(self._engine_combo)

        self._channel_combo = QComboBox()
        self._channel_combo.setMinimumWidth(220)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        sel_row.addWidget(self._lbl("Kanal:"))
        sel_row.addWidget(self._channel_combo)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setObjectName("btnBrowse")
        refresh_btn.setFixedWidth(36)
        refresh_btn.setToolTip("Listeyi tazele")
        refresh_btn.clicked.connect(self._refresh_all)
        sel_row.addWidget(refresh_btn)

        sel_row.addStretch()
        outer.addLayout(sel_row)

        # ── Run tablosu + aksiyon butonları ─────────────────────────────
        runs_card, runs_body = _card("📋  Bu Kanaldaki Run'lar")
        self._runs_table = _make_table(
            ["ID", "Run", "Tarih", "Ref", "RPM aralığı", "Slice"]
        )
        self._runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._runs_table.setSelectionMode(QTableWidget.SingleSelection)
        self._runs_table.itemSelectionChanged.connect(self._on_selection_changed)
        runs_body.addWidget(self._runs_table)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._set_ref_btn  = QPushButton("Referans olarak seç")
        self._set_meas_btn = QPushButton("Ölçüm olarak seç")
        for b in (self._set_ref_btn, self._set_meas_btn):
            b.setObjectName("btnBrowse")
            b.setEnabled(False)
        self._set_ref_btn.clicked.connect(self._mark_as_ref)
        self._set_meas_btn.clicked.connect(self._mark_as_meas)
        action_row.addWidget(self._set_ref_btn)
        action_row.addWidget(self._set_meas_btn)

        toggle_btn = QPushButton("DB'de referans bayrağını çevir ↻")
        toggle_btn.setObjectName("btnBrowse")
        toggle_btn.setToolTip("Seçili satırın is_reference değerini tersine çevirir.")
        toggle_btn.clicked.connect(self._toggle_reference_flag)
        action_row.addWidget(toggle_btn)
        action_row.addStretch()
        runs_body.addLayout(action_row)

        outer.addWidget(runs_card, stretch=1)

        # ── Seçim özeti + çalıştır ──────────────────────────────────────
        summary_card, summary_body = _card("🎯  Analiz")
        self._ref_label  = QLabel("Referans: —")
        self._meas_label = QLabel("Ölçüm:   —")
        for lbl in (self._ref_label, self._meas_label):
            lbl.setObjectName("fieldLabel")
            f = lbl.font()
            f.setBold(True)
            lbl.setFont(f)
            summary_body.addWidget(lbl)

        run_row = QHBoxLayout()
        self._run_btn = QPushButton("▶  Analizi Başlat")
        self._run_btn.setObjectName("btnPrimary")
        self._run_btn.setFixedHeight(40)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._run_analysis)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        summary_body.addLayout(run_row)

        outer.addWidget(summary_card)

        log_card, log_body = _card("📋  İşlem Günlüğü")
        self._log = LogPanel()
        self._log.setMaximumHeight(140)
        log_body.addWidget(self._log)
        outer.addWidget(log_card)

        self._overlay = LoadingOverlay(self)
        QTimer.singleShot(0, self._init_store)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    # ── DB yaşam döngüsü ──────────────────────────────────────────────────

    def _init_store(self) -> None:
        try:
            self._store = DataStore()
            self._refresh_all()
        except Exception as exc:
            logger.error("DataStore acilamadi: %s", exc)
            QMessageBox.critical(
                self, "Veritabanı Hatası", f"DataStore açılamadı:\n{exc}"
            )

    def runs_changed(self) -> None:
        """Veri Yükle sayfası yeni satır eklediğinde çağrılır."""
        self._refresh_all()

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Liste populate ────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        if self._store is None:
            return
        prev_engine = self._engine_combo.currentText()
        engines = self._store.list_engines()
        self._engine_combo.blockSignals(True)
        self._engine_combo.clear()
        self._engine_combo.addItems(engines)
        if prev_engine in engines:
            self._engine_combo.setCurrentText(prev_engine)
        self._engine_combo.blockSignals(False)
        self._on_engine_changed(self._engine_combo.currentText())

    def _on_engine_changed(self, engine_id: str) -> None:
        if self._store is None or not engine_id:
            self._channel_combo.clear()
            self._runs_table.setRowCount(0)
            return
        channels = self._store.list_channels(engine_id)
        prev_data = self._channel_combo.currentData()
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        for ch in channels:
            label = (
                f"{ch['sensor_location']} / {ch['axis']}   "
                f"({ch['n_runs']} run, {ch['n_refs']} ref)"
            )
            self._channel_combo.addItem(
                label, (ch["sensor_location"], ch["axis"])
            )
        if prev_data is not None:
            for i in range(self._channel_combo.count()):
                if self._channel_combo.itemData(i) == prev_data:
                    self._channel_combo.setCurrentIndex(i)
                    break
        self._channel_combo.blockSignals(False)
        self._on_channel_changed(self._channel_combo.currentIndex())

    def _on_channel_changed(self, idx: int) -> None:
        self._sel_ref_id  = None
        self._sel_meas_id = None
        self._update_summary()

        if self._store is None or idx < 0:
            self._runs_table.setRowCount(0)
            return
        data = self._channel_combo.itemData(idx)
        engine = self._engine_combo.currentText()
        if not engine or not data:
            self._runs_table.setRowCount(0)
            return
        location, axis = data
        rows = self._store.list_runs(
            engine_id=engine, sensor_location=location, axis=axis,
        )
        self._fill_runs_table(rows)

    def _fill_runs_table(self, rows) -> None:
        self._runs_table.setRowCount(0)
        for r in rows:
            i = self._runs_table.rowCount()
            self._runs_table.insertRow(i)
            id_item = _table_item(str(r.id), "#8b949e")
            id_item.setData(Qt.UserRole, int(r.id))
            self._runs_table.setItem(i, 0, id_item)
            self._runs_table.setItem(i, 1, _table_item(r.run_id, bold=True))
            date_str = r.measurement_date.isoformat() if r.measurement_date else "—"
            self._runs_table.setItem(i, 2, _table_item(date_str))
            if r.is_reference:
                self._runs_table.setItem(i, 3, _table_item("REF", "#3fb950", bold=True))
            else:
                self._runs_table.setItem(i, 3, _table_item("—", "#8b949e"))
            self._runs_table.setItem(
                i, 4, _table_item(f"{r.rpm_min:.0f} – {r.rpm_max:.0f}")
            )
            self._runs_table.setItem(i, 5, _table_item(str(r.n_slices), "#8b949e"))

    # ── Satır seçim aksiyonları ───────────────────────────────────────────

    def _selected_id(self) -> Optional[int]:
        items = self._runs_table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        return self._runs_table.item(row, 0).data(Qt.UserRole)

    def _on_selection_changed(self) -> None:
        has = self._selected_id() is not None
        self._set_ref_btn.setEnabled(has)
        self._set_meas_btn.setEnabled(has)

    def _mark_as_ref(self) -> None:
        sel = self._selected_id()
        if sel is None:
            return
        if sel == self._sel_meas_id:
            self._sel_meas_id = None
        self._sel_ref_id = sel
        self._update_summary()

    def _mark_as_meas(self) -> None:
        sel = self._selected_id()
        if sel is None:
            return
        if sel == self._sel_ref_id:
            self._sel_ref_id = None
        self._sel_meas_id = sel
        self._update_summary()

    def _toggle_reference_flag(self) -> None:
        sel = self._selected_id()
        if sel is None or self._store is None:
            return
        rows = [s for s in self._store.list_runs() if s.id == sel]
        if not rows:
            return
        new_state = not rows[0].is_reference
        self._store.set_reference(sel, new_state)
        self._log.append_log(
            f"id={sel} is_reference={'TRUE' if new_state else 'FALSE'}", "INFO",
        )
        self._on_channel_changed(self._channel_combo.currentIndex())

    def _update_summary(self) -> None:
        self._ref_label.setText(
            f"Referans: id={self._sel_ref_id}" if self._sel_ref_id else "Referans: —"
        )
        self._meas_label.setText(
            f"Ölçüm:   id={self._sel_meas_id}" if self._sel_meas_id else "Ölçüm:   —"
        )
        self._run_btn.setEnabled(
            self._sel_ref_id is not None and self._sel_meas_id is not None
            and self._sel_ref_id != self._sel_meas_id
        )

    # ── Analiz ────────────────────────────────────────────────────────────

    def _run_analysis(self) -> None:
        if self._sel_ref_id is None or self._sel_meas_id is None:
            return
        self._worker = DbAnalysisWorker(
            ref_run_id=self._sel_ref_id,
            meas_run_id=self._sel_meas_id,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._run_btn.setEnabled(False)
        self._overlay.show_loading("Analiz çalışıyor…")
        self._log.clear()
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._log.append_log(msg, "INFO")
        self._overlay._sub.setText(msg)

    def _on_finished(self, report, order_data, ref_order_data, run, ref_run) -> None:
        self._overlay.hide_loading()
        self._update_summary()
        self._log.append_log(
            f"✓ Tamamlandı — Skor: {report.overall_health_score}/100  "
            f"| Anomali: {len(report.anomalies)}",
            "SUCCESS",
        )
        self.analysis_done.emit(report, order_data, ref_order_data, run, ref_run)

    def _on_error(self, msg: str) -> None:
        self._overlay.hide_loading()
        self._update_summary()
        self._log.append_log(f"✕ Hata: {msg}", "ERROR")
        QMessageBox.critical(self, "Analiz Hatası", msg[:400])



# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: DB-BASED FLEET ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

class PageDbFleetAnalysis(QWidget):
    """
    DuckDB tabanlı filo analizi: tüm run'ları tabloda gösterir, lokasyon /
    eksen / referans filtreleri uygular, çoklu seçimle analiz başlatır.

    Her ölçüm run'ı için kanal-bazlı (lokasyon+eksen) otomatik referans
    seçilir — önce aynı motorda, yoksa herhangi bir motorda is_reference
    işaretli olan.

    ``runs_changed`` slot'u Veri Yükle sayfasından çağrılır.
    """

    analysis_done = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._worker: Optional[DbFleetAnalysisWorker] = None
        self._store: Optional[DataStore] = None
        self._all_rows: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        outer.addWidget(_page_header(
            "🚁  Filo Analizi",
            "Veritabanındaki run'lar arasından seçim yapın; her ölçüm için "
            "kanal-bazlı uygun referans otomatik bulunur.",
        ))
        outer.addWidget(Divider())

        # ── Filtreler ─────────────────────────────────────────────────────
        filt_row = QHBoxLayout()
        filt_row.setSpacing(8)

        from engine_config import LOCATION_CODES
        self._loc_filter = QComboBox()
        self._loc_filter.addItem("Tümü", None)
        for code in LOCATION_CODES:
            self._loc_filter.addItem(code, code)
        self._loc_filter.currentIndexChanged.connect(self._apply_filters)
        filt_row.addWidget(self._lbl("Lokasyon:"))
        filt_row.addWidget(self._loc_filter)

        self._axis_filter = QComboBox()
        self._axis_filter.addItem("Tümü", None)
        for ax in ("X", "Y", "Z"):
            self._axis_filter.addItem(ax, ax)
        self._axis_filter.currentIndexChanged.connect(self._apply_filters)
        filt_row.addWidget(self._lbl("Eksen:"))
        filt_row.addWidget(self._axis_filter)

        self._hide_refs = QCheckBox("Referansları gizle")
        self._hide_refs.toggled.connect(self._apply_filters)
        filt_row.addWidget(self._hide_refs)

        filt_row.addStretch()

        refresh_btn = QPushButton("⟳  Tazele")
        refresh_btn.setObjectName("btnBrowse")
        refresh_btn.clicked.connect(self._refresh_all)
        filt_row.addWidget(refresh_btn)

        outer.addLayout(filt_row)

        # ── Run tablosu (çoklu seçim) ────────────────────────────────────
        runs_card, runs_body = _card("📋  Veritabanındaki Run'lar")
        self._runs_table = _make_table(
            ["ID", "Motor", "Lokasyon", "Eksen", "Run", "Tarih", "Ref", "RPM"]
        )
        self._runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._runs_table.setSelectionMode(QTableWidget.ExtendedSelection)
        runs_body.addWidget(self._runs_table)

        action_row = QHBoxLayout()
        self._run_btn = QPushButton("▶  Seçileni Analiz Et")
        self._run_btn.setObjectName("btnPrimary")
        self._run_btn.setFixedHeight(40)
        self._run_btn.clicked.connect(self._run_fleet)
        action_row.addWidget(self._run_btn)
        self._sel_count = QLabel("0 satır seçili")
        self._sel_count.setObjectName("fieldLabel")
        action_row.addWidget(self._sel_count)
        action_row.addStretch()
        runs_body.addLayout(action_row)

        self._runs_table.itemSelectionChanged.connect(self._update_sel_count)

        outer.addWidget(runs_card, stretch=2)

        # ── Sonuç ve log paneli ─────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, stretch=1)

        score_card, score_body = _card("Motor Skorları")
        self._score_table = _make_table(["Motor ID", "Skor", "Durum"])
        score_body.addWidget(self._score_table)
        cols.addWidget(score_card, stretch=1)

        log_card, log_body = _card("📋  İlerleme")
        self._log = LogPanel()
        log_body.addWidget(self._log)
        cols.addWidget(log_card, stretch=1)

        self._overlay = LoadingOverlay(self)
        QTimer.singleShot(0, self._init_store)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _init_store(self) -> None:
        try:
            self._store = DataStore()
            self._refresh_all()
        except Exception as exc:
            logger.error("DataStore acilamadi: %s", exc)
            QMessageBox.critical(
                self, "Veritabanı Hatası", f"DataStore açılamadı:\n{exc}"
            )

    def runs_changed(self) -> None:
        self._refresh_all()

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    # ── Liste populate ────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        if self._store is None:
            return
        self._all_rows = list(self._store.list_runs())
        self._apply_filters()

    def _apply_filters(self) -> None:
        loc = self._loc_filter.currentData()
        axis = self._axis_filter.currentData()
        hide_refs = self._hide_refs.isChecked()

        rows = []
        for r in self._all_rows:
            if loc is not None and r.sensor_location != loc:
                continue
            if axis is not None and r.axis != axis:
                continue
            if hide_refs and r.is_reference:
                continue
            rows.append(r)

        self._runs_table.setRowCount(0)
        for r in rows:
            i = self._runs_table.rowCount()
            self._runs_table.insertRow(i)
            id_item = _table_item(str(r.id), "#8b949e")
            id_item.setData(Qt.UserRole, int(r.id))
            self._runs_table.setItem(i, 0, id_item)
            self._runs_table.setItem(i, 1, _table_item(r.engine_id, bold=True))
            self._runs_table.setItem(i, 2, _table_item(r.sensor_location))
            self._runs_table.setItem(i, 3, _table_item(r.axis))
            self._runs_table.setItem(i, 4, _table_item(r.run_id))
            date_str = r.measurement_date.isoformat() if r.measurement_date else "—"
            self._runs_table.setItem(i, 5, _table_item(date_str))
            if r.is_reference:
                self._runs_table.setItem(i, 6, _table_item("REF", "#3fb950", bold=True))
            else:
                self._runs_table.setItem(i, 6, _table_item("—", "#8b949e"))
            self._runs_table.setItem(
                i, 7, _table_item(f"{r.rpm_min:.0f}–{r.rpm_max:.0f}")
            )
        self._update_sel_count()

    def _selected_ids(self) -> List[int]:
        ids: set = set()
        for it in self._runs_table.selectedItems():
            if it.column() == 0:
                ids.add(int(it.data(Qt.UserRole)))
        return sorted(ids)

    def _update_sel_count(self) -> None:
        n = len(self._selected_ids())
        self._sel_count.setText(f"{n} satır seçili")
        self._run_btn.setEnabled(n > 0)

    # ── Analiz ────────────────────────────────────────────────────────────

    def _run_fleet(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.warning(self, "Seçim yok", "Analiz için en az bir satır seçin.")
            return
        self._worker = DbFleetAnalysisWorker(meas_run_ids=ids)
        self._worker.progress.connect(lambda m: self._log.append_log(m))
        self._worker.engine_done.connect(self._on_engine_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._run_btn.setEnabled(False)
        self._score_table.setRowCount(0)
        self._log.clear()
        self._overlay.show_loading(f"Filo analizi… ({len(ids)} run)")
        self._worker.start()

    def _on_engine_done(self, eid: str, score: float) -> None:
        i = self._score_table.rowCount()
        self._score_table.insertRow(i)
        color = "#3fb950" if score >= 80 else "#d29922" if score >= 55 else "#f85149"
        status = "✓ OK" if score >= 80 else "⚠ Warning" if score >= 55 else "✕ Critical"
        self._score_table.setItem(i, 0, _table_item(eid))
        self._score_table.setItem(i, 1, _table_item(f"{score:.0f}/100", color, bold=True))
        self._score_table.setItem(i, 2, _table_item(status, color))

    def _on_finished(self, reports, ref_run) -> None:
        self._overlay.hide_loading()
        self._update_sel_count()
        self._log.append_log(
            f"✓ Filo analizi tamamlandı — {len(reports)} motor", "SUCCESS"
        )
        self.analysis_done.emit(reports, ref_run)

    def _on_error(self, msg: str) -> None:
        self._overlay.hide_loading()
        self._update_sel_count()
        self._log.append_log(f"✕ Hata: {msg}", "ERROR")
        QMessageBox.critical(self, "Hata", msg[:400])



# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: DEMO RUN
# ─────────────────────────────────────────────────────────────────────────────

class PageDemoRun(QWidget):

    analysis_done = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self._worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        outer.addWidget(_page_header(
            "⚡  Demo Çalıştır",
            "Sentetik veri ile 4 motoru (dişli kutusu, pervane, yanma anomalisi, sağlıklı) analiz edin.",
        ))
        outer.addWidget(Divider())

        # Demo açıklama kartı
        info_card, info_body = _card("ℹ️  Demo Hakkında")
        desc = QLabel(
            "Demo modu şu sentetik motorları oluşturur:\n\n"
            "  •  ENG-042  —  Dişli Kutusu Aşınması  (29× + 28/30× yan bantlar + 58× yüksek)\n"
            "  •  ENG-043  —  Pervane Dengesizliği  (0.59× ve 1.77× yüksek)\n"
            "  •  ENG-044  —  Yanma Anomalisi / Misfire  (0.5× ve 2× yüksek)\n"
            "  •  ENG-045  —  Sağlıklı Motor  (referansa yakın)\n\n"
            "Gerçek verilerle kullanım için 'Tek Motor' veya 'Filo Analizi' sayfasını kullanın."
        )
        desc.setObjectName("fieldLabel")
        desc.setWordWrap(True)
        info_body.addWidget(desc)
        outer.addWidget(info_card)

        # Run button
        run_row = QHBoxLayout()
        self._run_btn = QPushButton("⚡  Demo Analizi Başlat")
        self._run_btn.setObjectName("btnSuccess")
        self._run_btn.setFixedHeight(46)
        self._run_btn.setFixedWidth(280)
        self._run_btn.clicked.connect(self._run_demo)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        outer.addLayout(run_row)

        # Log + score
        cols = QHBoxLayout()
        cols.setSpacing(16)
        outer.addLayout(cols, stretch=1)

        log_card, log_body = _card("📋  İşlem Günlüğü")
        self._log = LogPanel()
        log_body.addWidget(self._log)
        cols.addWidget(log_card, stretch=1)

        score_card, score_body = _card("Motor Sonuçları")
        self._score_table = _make_table(["Motor ID", "Skor", "Beklenen Arıza"])
        score_body.addWidget(self._score_table)
        cols.addWidget(score_card, stretch=1)

        self._overlay = LoadingOverlay(self)

    def resizeEvent(self, event):
        self._overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def _run_demo(self):
        self._worker = DemoWorker()
        self._worker.progress.connect(lambda m: self._log.append_log(m))
        self._worker.engine_done.connect(self._on_engine_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._run_btn.setEnabled(False)
        self._score_table.setRowCount(0)
        self._overlay.show_loading("Demo verisi hazırlanıyor…")
        self._log.clear()
        self._worker.start()

    def _on_engine_done(self, eid: str, score: float):
        row = self._score_table.rowCount()
        self._score_table.insertRow(row)
        color = "#3fb950" if score >= 80 else "#d29922" if score >= 55 else "#f85149"
        fault_hints = {
            "ENG-042": "Dişli Kutusu Aşınması",
            "ENG-043": "Pervane Dengesizliği",
            "ENG-044": "Yanma Anomalisi",
            "ENG-045": "Sağlıklı",
        }
        hint = next((v for k, v in fault_hints.items() if k in eid), "—")
        self._score_table.setItem(row, 0, _table_item(eid))
        self._score_table.setItem(row, 1, _table_item(f"{score:.0f}/100", color, bold=True))
        self._score_table.setItem(row, 2, _table_item(hint))

    def _on_finished(self, reports, ref_run):
        self._overlay.hide_loading()
        self._run_btn.setEnabled(True)
        self._log.append_log("✓ Demo tamamlandı — Sonuçlar sayfasına yönlendiriliyorsunuz…", "SUCCESS")
        self.analysis_done.emit(reports, ref_run)

    def _on_error(self, msg: str):
        self._overlay.hide_loading()
        self._run_btn.setEnabled(True)
        self._log.append_log(f"✕ Hata: {msg}", "ERROR")
        QMessageBox.critical(self, "Demo Hatası", msg[:400])


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: RESULTS
# ─────────────────────────────────────────────────────────────────────────────

class PageResults(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        outer.addWidget(_page_header(
            "📊  Analiz Sonuçları",
            "Waterfall grafiği, order karşılaştırması ve teşhis raporu.",
        ))
        outer.addWidget(Divider())

        # Engine selector (fleet mode)
        selector_row = QHBoxLayout()
        selector_row.setSpacing(10)
        lbl = QLabel("Motor seç:")
        lbl.setObjectName("fieldLabel")
        selector_row.addWidget(lbl)
        self._engine_combo = QComboBox()
        self._engine_combo.setFixedWidth(260)
        self._engine_combo.currentTextChanged.connect(self._on_engine_selected)
        selector_row.addWidget(self._engine_combo)
        selector_row.addStretch()
        outer.addLayout(selector_row)

        # Main splitter: left=plots, right=diagnosis
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        outer.addWidget(splitter, stretch=1)

        # ── Left: plot tabs ───────────────────────────────────────────────
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)

        self._plot_tabs = QTabWidget()
        self._plot_tabs.setObjectName("plotTabs")
        plot_layout.addWidget(self._plot_tabs)

        # ── Waterfall tab ────────────────────────────────────────────────
        wf_tab = QWidget()
        wf_layout = QVBoxLayout(wf_tab)
        wf_layout.setContentsMargins(0, 0, 0, 0)
        wf_layout.setSpacing(0)
        self._wf_controls = WaterfallControlBar()
        self._wf_controls.refresh_requested.connect(self._on_wf_refresh)
        wf_layout.addWidget(self._wf_controls)
        self._canvas_waterfall = MatplotlibCanvas(show_toolbar=True)
        wf_layout.addWidget(self._canvas_waterfall, stretch=1)

        # Order comparison tab — scrollable for many-subplot figures
        self._canvas_orders = MatplotlibCanvas(scrollable=True)
        self._canvas_card   = MatplotlibCanvas()

        self._plot_tabs.addTab(wf_tab,                  "🌊  Waterfall")
        self._plot_tabs.addTab(self._canvas_orders,     "📈  Order Karşılaştırma")
        self._plot_tabs.addTab(self._canvas_card,       "📋  Tanı Kartı")

        # Cache the current run so the waterfall can be re-rendered with new bounds
        self._current_run = None

        splitter.addWidget(plot_widget)

        # ── Right: diagnosis panel ────────────────────────────────────────
        diag_scroll = QScrollArea()
        diag_scroll.setWidgetResizable(True)
        diag_scroll.setFrameShape(QFrame.NoFrame)
        self._diag_widget = DiagnosisPanel()
        diag_scroll.setWidget(self._diag_widget)
        splitter.addWidget(diag_scroll)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Internal state
        self._reports: Dict = {}
        self._ref_run = None
        self._current_report = None

    def show_single(self, report, order_data, ref_order_data, run, ref_run):
        """Display results for a single engine analysis."""
        self._reports = {report.engine_id: report}
        self._ref_run = ref_run
        self._engine_combo.clear()
        self._engine_combo.addItem(report.engine_id)
        self._render_report(report, run, ref_run, order_data, ref_order_data)

    def show_fleet(self, reports: Dict, ref_run):
        """Display fleet results — populate engine selector."""
        self._reports = reports
        self._ref_run = ref_run
        self._engine_combo.clear()
        for eid in sorted(reports.keys()):
            self._engine_combo.addItem(eid)

    def _on_engine_selected(self, eid: str):
        if not eid or eid not in self._reports:
            return
        report = self._reports[eid]
        # We need to rebuild run/order_data for fleet engines
        # For now we render diagnosis panel and placeholder plots
        self._diag_widget.set_report(report)
        self._render_plots_for_report(report)

    def _render_report(self, report, run, ref_run, order_data, ref_order_data):
        """Full render with actual run data."""
        self._diag_widget.set_report(report)
        self._render_plots(report, run, ref_run, order_data, ref_order_data)

    def _render_plots(self, report, run, ref_run, order_data, ref_order_data):
        from plots import plot_waterfall, plot_order_comparison, plot_diagnostic_card

        self._current_run = run
        if run is not None:
            self._wf_controls.set_rpm_range(*run.rpm_range)

        try:
            fig_wf = plot_waterfall(run)
            self._canvas_waterfall.set_figure(fig_wf)
        except Exception as e:
            logger.warning("Waterfall plot error: %s", e)

        try:
            fig_ord = plot_order_comparison(order_data, ref_order_data, report.anomalies)
            self._canvas_orders.set_figure(fig_ord)
        except Exception as e:
            logger.warning("Order plot error: %s", e)

        try:
            fig_card = plot_diagnostic_card(report)
            self._canvas_card.set_figure(fig_card)
        except Exception as e:
            logger.warning("Card plot error: %s", e)

    def _on_wf_refresh(self, f_min, f_max, r_min, r_max):
        """User changed Hz/RPM bounds — re-render waterfall in place."""
        if self._current_run is None:
            return
        from plots import plot_waterfall
        kwargs = {}
        if f_min is not None:
            kwargs["freq_min"] = f_min
        if f_max is not None:
            kwargs["freq_max"] = f_max
        if r_min is not None:
            kwargs["rpm_min"] = r_min
        if r_max is not None:
            kwargs["rpm_max"] = r_max
        try:
            fig_wf = plot_waterfall(self._current_run, **kwargs)
            self._canvas_waterfall.set_figure(fig_wf)
        except Exception as e:
            logger.warning("Waterfall refresh error: %s", e)

    def _render_plots_for_report(self, report):
        """For fleet: render only the diagnostic card (no raw run data)."""
        from plots import plot_diagnostic_card
        try:
            fig_card = plot_diagnostic_card(report)
            self._canvas_card.set_figure(fig_card)
        except Exception as e:
            logger.warning("Card error: %s", e)
        self._diag_widget.set_report(report)


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNOSIS PANEL  (right side of results page)
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosisPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 16)
        layout.setSpacing(16)

        # Health score + summary
        score_card, score_body = _card("Sağlık Skoru")
        score_row = QHBoxLayout()
        self._dial = HealthScoreDial(100)
        score_row.addWidget(self._dial)
        summary_col = QVBoxLayout()
        self._summary_label = QLabel("Analiz bekleniyor…")
        self._summary_label.setWordWrap(True)
        self._summary_label.setObjectName("fieldLabel")
        summary_col.addWidget(self._summary_label)
        self._engine_id_label = QLabel("")
        self._engine_id_label.setObjectName("pageTitle")
        summary_col.addWidget(self._engine_id_label)
        score_row.addLayout(summary_col, stretch=1)
        score_body.addLayout(score_row)
        layout.addWidget(score_card)

        # Fault diagnoses table
        fault_card, fault_body = _card("Teşhis Edilen Arızalar")
        self._fault_table = _make_table(["Arıza", "Kategori", "Güven", "Severity"])
        self._fault_table.setMinimumHeight(140)
        self._fault_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._fault_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._fault_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._fault_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        fault_body.addWidget(self._fault_table)
        layout.addWidget(fault_card)

        # Anomalies table
        anom_card, anom_body = _card("Anomali Listesi")
        self._anom_table = _make_table(["Order", "RPM", "Frekans", "Oran", "Severity"])
        self._anom_table.setMinimumHeight(140)
        anom_body.addWidget(self._anom_table)
        layout.addWidget(anom_card)

        # Recommendations
        rec_card, rec_body = _card("Öneriler")
        self._rec_text = QTextEdit()
        self._rec_text.setReadOnly(True)
        self._rec_text.setObjectName("logPanel")
        self._rec_text.setMinimumHeight(120)
        rec_body.addWidget(self._rec_text)
        layout.addWidget(rec_card)

    def set_report(self, report) -> None:
        # Score
        self._dial.set_score(report.overall_health_score)
        self._engine_id_label.setText(report.engine_id)
        self._summary_label.setText(report.summary)

        # Fault table
        self._fault_table.setRowCount(0)
        for d in report.fault_diagnoses:
            row = self._fault_table.rowCount()
            self._fault_table.insertRow(row)
            color = _severity_color(d["severity"])
            self._fault_table.setItem(row, 0, _table_item(d["fault_name"]))
            self._fault_table.setItem(row, 1, _table_item(d["category"]))
            self._fault_table.setItem(row, 2, _table_item(f"{int(d['confidence']*100)}%"))
            self._fault_table.setItem(row, 3, _table_item(d["severity"], color, bold=True))

        # Anomaly table
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

        # Recommendations
        recs = "\n\n".join(
            f"{'→'} {r}" for r in report.recommendations
        ) or "Anormallik tespit edilmedi."
        self._rec_text.setPlainText(recs)


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE: ENGINE CONFIG VIEWER
# ─────────────────────────────────────────────────────────────────────────────

class PageEngineConfig(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageContent")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        outer.addWidget(_page_header(
            "⚙️  Motor Konfigürasyonu",
            "engine_config.py dosyasındaki motor-spesifik tanımları görüntüleyin.",
        ))
        outer.addWidget(Divider())

        tabs = QTabWidget()
        outer.addWidget(tabs, stretch=1)

        # Tab 1: Order Tanımları
        order_widget = QWidget()
        ol = QVBoxLayout(order_widget)
        ol.setContentsMargins(12, 12, 12, 12)
        order_tbl = _make_table(["Order", "İsim", "Kaynak", "Açıklama", "Arıza Göstergeleri"])
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
        tabs.addTab(order_widget, "Order Tanımları")

        # Tab 2: Arıza İmzaları
        fault_widget = QWidget()
        fl = QVBoxLayout(fault_widget)
        fl.setContentsMargins(12, 12, 12, 12)
        fault_tbl = _make_table(["Arıza", "Kategori", "Birincil Orders", "İkincil Orders", "Eşik (×)"])
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
        tabs.addTab(fault_widget, "Arıza İmzaları")

        # Tab 3: Motor Parametreleri
        param_widget = QWidget()
        pl = QVBoxLayout(param_widget)
        pl.setContentsMargins(12, 12, 12, 12)

        from engine_config import ENGINE_CONFIG
        param_tbl = _make_table(["Parametre", "Değer"])
        param_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        param_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        for key, val in ENGINE_CONFIG.items():
            row = param_tbl.rowCount()
            param_tbl.insertRow(row)
            param_tbl.setItem(row, 0, _table_item(str(key), "#8b949e"))
            param_tbl.setItem(row, 1, _table_item(str(val)))

        pl.addWidget(param_tbl)
        tabs.addTab(param_widget, "Motor Parametreleri")
