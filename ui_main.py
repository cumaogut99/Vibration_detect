"""
ui_main.py — PySide6 Ana Pencere

Kurulum:
    pip install PySide6 matplotlib numpy scipy

Başlatma:
    python ui_main.py
"""

import sys
import logging
import traceback
from pathlib import Path
from typing import Optional, Dict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QFrame, QScrollArea,
    QSizePolicy, QStatusBar, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize
from PySide6.QtGui import QFont, QIcon, QColor, QPalette, QPixmap

# ── Backend imports ────────────────────────────────────────────────────────
# Backend modullerini onceden yukle — circular import'u onler
import models          # noqa: F401 — ilk yuklenmeli
import engine_config   # noqa: F401
import importers       # noqa: F401
import analysis        # noqa: F401

from ui_widgets import (
    NavButton, SectionTitle, Divider, StatusBadge,
    EngineCard, LoadingOverlay, LogPanel,
)
from ui_pages import (
    PageSingleAnalysis,
    PageFleetAnalysis,
    PageDemoRun,
    PageResults,
    PageEngineConfig,
)
from ui_styles import STYLESHEET, PALETTE_COLORS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  APPLICATION ENTRY
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """GUI uygulamasını başlatır. main.py'den veya doğrudan çağrılabilir."""
    # High-DPI
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

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────
        self._sidebar = self._build_sidebar()
        root_layout.addWidget(self._sidebar)

        # ── Content area ──────────────────────────────────────────────────
        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, stretch=1)

        # ── Pages ─────────────────────────────────────────────────────────
        self._page_single  = PageSingleAnalysis(self)
        self._page_fleet   = PageFleetAnalysis(self)
        self._page_demo    = PageDemoRun(self)
        self._page_results = PageResults(self)
        self._page_config  = PageEngineConfig(self)

        self._stack.addWidget(self._page_single)   # index 0
        self._stack.addWidget(self._page_fleet)    # index 1
        self._stack.addWidget(self._page_demo)     # index 2
        self._stack.addWidget(self._page_results)  # index 3
        self._stack.addWidget(self._page_config)   # index 4

        # Connect page signals to result viewer
        self._page_single.analysis_done.connect(self._on_analysis_done)
        self._page_fleet.analysis_done.connect(self._on_fleet_done)
        self._page_demo.analysis_done.connect(self._on_fleet_done)

        # ── Status bar ────────────────────────────────────────────────────
        self._status = QStatusBar()
        self._status.setObjectName("statusBar")
        self.setStatusBar(self._status)
        self._status.showMessage("Hazır  ·  Veri dosyası yükleyin veya Demo çalıştırın")

        # Select first page
        self._select_page(0)

    # ── Sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo / title
        title_frame = QFrame()
        title_frame.setObjectName("sidebarTitle")
        title_frame.setFixedHeight(72)
        tl = QVBoxLayout(title_frame)
        tl.setContentsMargins(20, 14, 20, 14)
        logo = QLabel("✈  VibAnalyzer")
        logo.setObjectName("logoLabel")
        sub  = QLabel("Piston Engine Diagnostics")
        sub.setObjectName("logoSub")
        tl.addWidget(logo)
        tl.addWidget(sub)
        layout.addWidget(title_frame)

        # Divider
        layout.addWidget(Divider())

        # Nav section label
        nav_label = QLabel("  ANALİZ")
        nav_label.setObjectName("navSection")
        layout.addWidget(nav_label)

        # Nav buttons
        self._nav_buttons: list[NavButton] = []

        items = [
            ("🔍  Tek Motor Analizi",  0),
            ("🚁  Filo Analizi",       1),
            ("⚡  Demo Çalıştır",      2),
        ]
        for label, idx in items:
            btn = NavButton(label, idx)
            btn.clicked.connect(lambda _, i=idx: self._select_page(i))
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addSpacing(16)
        layout.addWidget(Divider())

        nav_label2 = QLabel("  ARAÇLAR")
        nav_label2.setObjectName("navSection")
        layout.addWidget(nav_label2)

        btn_results = NavButton("📊  Son Sonuçlar", 3)
        btn_results.clicked.connect(lambda: self._select_page(3))
        self._nav_buttons.append(btn_results)
        layout.addWidget(btn_results)

        btn_config = NavButton("⚙️  Motor Konfigürasyonu", 4)
        btn_config.clicked.connect(lambda: self._select_page(4))
        self._nav_buttons.append(btn_config)
        layout.addWidget(btn_config)

        layout.addStretch()

        # Version footer
        ver = QLabel("v1.0  ·  4-cyl 4-stroke")
        ver.setObjectName("sidebarVer")
        ver.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver)
        layout.addSpacing(12)

        return sidebar

    def _select_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for btn in self._nav_buttons:
            btn.setActive(btn.page_index == index)

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _on_analysis_done(self, report, order_data, ref_order_data, run, ref_run) -> None:
        self._page_results.show_single(report, order_data, ref_order_data, run, ref_run)
        self._select_page(3)
        self._status.showMessage(
            f"Analiz tamamlandı  ·  {report.engine_id}  ·  "
            f"Skor: {report.overall_health_score}/100  ·  "
            f"Anomali: {len(report.anomalies)}"
        )

    def _on_fleet_done(self, reports: dict, ref_run) -> None:
        self._page_results.show_fleet(reports, ref_run)
        self._select_page(3)
        self._status.showMessage(
            f"Filo analizi tamamlandı  ·  {len(reports)} motor"
        )

    def show_status(self, msg: str) -> None:
        self._status.showMessage(msg)


if __name__ == "__main__":
    main()
