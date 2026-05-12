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

from ui_widgets import (
    Divider, ChannelStore, TopTabButton,
)
from ui_pages import (
    PageDataManagement,
    PageEngineConfig,
    PageAnalysis,
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
        self._page_log     = PageLog(self)

        self._stack.addWidget(self._page_data)    # index 0
        self._stack.addWidget(self._page_config)  # index 1
        self._stack.addWidget(self._page_analyze) # index 2
        self._stack.addWidget(self._page_log)     # index 3

        # Sayfalardan gelen log mesajlarini Log sayfasina yonlendir
        self._page_data.log_message.connect(self._on_log)
        self._page_analyze.log_message.connect(self._on_log)

        # Durum cubugu
        self._status = QStatusBar()
        self._status.setObjectName("statusBar")
        self.setStatusBar(self._status)
        self._status.showMessage("Hazir  ·  Veri Yonetimi'nden bir kanal yukleyin")

        # Yuklenmis kanal sayisini durum cubugunda goster
        self._store.channel_added.connect(self._refresh_status)
        self._store.channel_removed.connect(self._refresh_status)

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
            ("📋  Log",                   3),
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
        self._status.showMessage(f"Yuklenmis kanal sayisi: {n}")

    def show_status(self, msg: str) -> None:
        self._status.showMessage(msg)


if __name__ == "__main__":
    main()
