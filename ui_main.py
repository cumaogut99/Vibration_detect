"""
ui_main.py — PySide6 Ana Pencere

Kurulum:
    pip install PySide6 matplotlib numpy scipy

Baslatma:
    python ui_main.py
"""

import sys
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QFrame, QStatusBar,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

# Backend modullerini onceden yukle — circular import'u onler
import models          # noqa: F401
import engine_config   # noqa: F401
import importers       # noqa: F401
import analysis        # noqa: F401

from ui_widgets import ChannelStore, TopTabButton
from ui_pages import (
    PageDataManagement,
    PageEngineConfig,
    PageAnalysis,
    PageMaxHold,
    PageLog,
)
from ui_styles import STYLESHEET, PALETTE_COLORS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  APPLICATION ENTRY
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("VibrationAnalyzer")
    app.setApplicationDisplayName("Aircraft Vibration Analyzer")

    _apply_dark_palette(app)
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def _apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    c = PALETTE_COLORS
    palette.setColor(QPalette.Window,          QColor(c["bg"]))
    palette.setColor(QPalette.WindowText,      QColor(c["text"]))
    palette.setColor(QPalette.Base,            QColor(c["surface"]))
    palette.setColor(QPalette.AlternateBase,   QColor(c["surface_alt"]))
    palette.setColor(QPalette.Text,            QColor(c["text"]))
    palette.setColor(QPalette.Button,          QColor(c["surface"]))
    palette.setColor(QPalette.ButtonText,      QColor(c["text"]))
    palette.setColor(QPalette.Highlight,       QColor(c["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor(c["muted"]))
    palette.setColor(QPalette.ToolTipBase,     QColor(c["surface"]))
    palette.setColor(QPalette.ToolTipText,     QColor(c["text"]))
    app.setPalette(palette)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("✈  Aircraft Vibration Analyzer")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

        # Tum sayfalarin paylastigi merkezi kanal deposu
        self._store = ChannelStore(self)

        # Kalici DuckDB deposu (yoksa sessizce devre disi)
        self._db = None
        self._key_to_db_id: dict[str, int] = {}
        self._loading_from_db = False
        try:
            from db_layer import DataStore
            self._db = DataStore()
            logger.info("DuckDB deposu acildi: %s", self._db.db_path)
        except Exception as exc:
            logger.warning("DuckDB devre disi: %s", exc)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Ust sekme cubugu ──────────────────────────────────────────────
        tab_bar = self._build_top_tabbar()
        root_layout.addWidget(tab_bar)

        # ── Icerik alani ──────────────────────────────────────────────────
        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, stretch=1)

        # ── Sayfalar ──────────────────────────────────────────────────────
        self._page_data    = PageDataManagement(self._store, self)
        self._page_config  = PageEngineConfig(self)
        self._page_analyze = PageAnalysis(self._store, self)
        self._page_maxhold = PageMaxHold(self._store, self)
        self._page_log     = PageLog(self)

        self._stack.addWidget(self._page_data)    # index 0
        self._stack.addWidget(self._page_config)  # index 1
        self._stack.addWidget(self._page_analyze) # index 2
        self._stack.addWidget(self._page_maxhold) # index 3
        self._stack.addWidget(self._page_log)     # index 4

        # Sayfalardan gelen log mesajlarini Log sayfasina yonlendir
        self._page_data.log_message.connect(self._on_log)
        self._page_analyze.log_message.connect(self._on_log)
        self._page_maxhold.log_message.connect(self._on_log)

        # Durum cubugu
        self._status = QStatusBar()
        self._status.setObjectName("statusBar")
        self.setStatusBar(self._status)

        # DuckDB persist hook'lari
        self._store.channel_added.connect(self._persist_channel)
        self._store.channel_removed.connect(self._delete_channel)
        self._store.channel_added.connect(self._refresh_status)
        self._store.channel_removed.connect(self._refresh_status)

        # Mevcut DB icerigini in-memory store'a yukle
        self._load_existing_channels_from_db()

        if self._db is not None:
            self._status.showMessage(
                f"Hazir  ·  DB: {self._db.db_path}  ·  "
                f"Yuklenmis kanal: {len(self._store)}"
            )
        else:
            self._status.showMessage(
                "Hazir  ·  (DuckDB pasif — kalici saklama yok)"
            )

        # Ilk sayfa
        self._select_page(0)

    # ── Top tabbar ─────────────────────────────────────────────────────────

    def _build_top_tabbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topTabBar")
        bar.setFixedHeight(54)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 0)
        layout.setSpacing(4)

        # Logo
        logo = QLabel("✈  VibAnalyzer")
        logo.setObjectName("logoLabel")
        layout.addWidget(logo)
        layout.addSpacing(24)

        # 4 sekme
        self._tab_buttons: list[TopTabButton] = []
        items = [
            ("📂  Veri Yonetimi",       0),
            ("⚙️  Motor Konfigurasyonu", 1),
            ("📈  Analiz",                2),
            ("📊  Max Hold",             3),
            ("📋  Log",                   4),
        ]
        for label, idx in items:
            btn = TopTabButton(label, idx)
            btn.clicked.connect(lambda _, i=idx: self._select_page(i))
            self._tab_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()

        ver = QLabel("v2.0  ·  4-cyl 4-stroke")
        ver.setObjectName("sidebarVer")
        layout.addWidget(ver)

        return bar

    def _select_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for btn in self._tab_buttons:
            btn.setActive(btn.page_index == index)

    # ── Log yonlendirme ───────────────────────────────────────────────────

    def _on_log(self, msg: str, level: str) -> None:
        self._page_log.append(msg, level)
        if level in ("SUCCESS", "ERROR"):
            self._status.showMessage(msg, 5000)

    def _refresh_status(self, *_args) -> None:
        n = len(self._store)
        if self._db is not None:
            self._status.showMessage(
                f"DB: {self._db.db_path}  ·  Yuklenmis kanal: {n}"
            )
        else:
            self._status.showMessage(f"Yuklenmis kanal: {n}")

    def show_status(self, msg: str) -> None:
        self._status.showMessage(msg)

    # ── DuckDB kalici saklama ─────────────────────────────────────────────

    def _persist_channel(self, key: str, run) -> None:
        """ChannelStore'a eklenen kanali DuckDB'ye yaz."""
        if self._db is None or self._loading_from_db:
            return
        if key in self._key_to_db_id:
            return
        try:
            src = run.metadata.get("source_file") if run.metadata else None
            db_id = self._db.insert_run(run, source_file=src)
            self._key_to_db_id[key] = db_id
            self._page_log.append(
                f"💾  DB'ye kaydedildi (id={db_id}): {key}", "INFO"
            )
        except Exception as exc:
            logger.warning("DB persist hatasi: %s", exc)
            self._page_log.append(f"⚠  DB persist hatasi: {exc}", "WARNING")

    def _delete_channel(self, key: str) -> None:
        """ChannelStore'dan kaldirilan kanali DuckDB'den de sil."""
        if self._db is None:
            return
        db_id = self._key_to_db_id.pop(key, None)
        if db_id is None:
            return
        try:
            self._db.delete_run(db_id)
            self._page_log.append(
                f"🗑  DB'den silindi (id={db_id}): {key}", "INFO"
            )
        except Exception as exc:
            logger.warning("DB delete hatasi: %s", exc)

    def _load_existing_channels_from_db(self) -> None:
        """Uygulama acilirken DuckDB'deki kayitli kanallari belege yukler."""
        if self._db is None:
            return
        self._loading_from_db = True
        try:
            summaries = self._db.list_runs()
            for summary in summaries:
                try:
                    run = self._db.get_run(summary.id)
                except Exception as exc:
                    logger.warning("DB run %d yuklenemedi: %s", summary.id, exc)
                    continue
                key = self._store.add(run)
                self._key_to_db_id[key] = summary.id
            if summaries:
                logger.info("DB'den %d kanal yuklendi", len(summaries))
        finally:
            self._loading_from_db = False

    # ── Kapanis ───────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        try:
            if self._db is not None:
                self._db.close()
        except Exception:
            pass
        super().closeEvent(event)


if __name__ == "__main__":
    main()
