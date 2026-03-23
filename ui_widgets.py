"""
ui_widgets.py — Tekrar kullanılabilir PySide6 widget'ları.

Tüm sayfalar bu widget'ları kullanır.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QSizePolicy, QPlainTextEdit, QProgressBar,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  NAV BUTTON
# ─────────────────────────────────────────────────────────────────────────────

class NavButton(QPushButton):
    """Sidebar navigation button with active state."""

    def __init__(self, label: str, page_index: int, parent=None):
        super().__init__(label, parent)
        self.page_index = page_index
        self.setObjectName("navBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(False)
        self._active = False

    def setActive(self, active: bool) -> None:
        self._active = active
        self.setProperty("active", "true" if active else "false")
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)


# ─────────────────────────────────────────────────────────────────────────────
#  DIVIDER
# ─────────────────────────────────────────────────────────────────────────────

class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION TITLE
# ─────────────────────────────────────────────────────────────────────────────

class SectionTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setObjectName("sectionTitle")


# ─────────────────────────────────────────────────────────────────────────────
#  STATUS BADGE
# ─────────────────────────────────────────────────────────────────────────────

class StatusBadge(QLabel):
    """Colored severity badge: OK / WARNING / CRITICAL."""

    _MAP = {
        "ok":       ("badgeOk",       "✓  OK"),
        "warning":  ("badgeWarning",  "⚠  WARNING"),
        "critical": ("badgeCritical", "✕  CRITICAL"),
    }

    def __init__(self, status: str = "ok", parent=None):
        super().__init__(parent)
        self.set_status(status)
        self.setAlignment(Qt.AlignCenter)

    def set_status(self, status: str) -> None:
        key = status.lower()
        obj_name, text = self._MAP.get(key, ("badgeOk", status.upper()))
        self.setObjectName(obj_name)
        self.setText(text)
        self.style().unpolish(self)
        self.style().polish(self)


# ─────────────────────────────────────────────────────────────────────────────
#  HEALTH SCORE DIAL
# ─────────────────────────────────────────────────────────────────────────────

class HealthScoreDial(QWidget):
    """Circular gauge showing health score 0–100."""

    def __init__(self, score: float = 100.0, parent=None):
        super().__init__(parent)
        self._score = score
        self.setFixedSize(120, 120)

    def set_score(self, score: float) -> None:
        self._score = score
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        margin = 10
        rect_size = min(w, h) - margin * 2

        # Background arc
        bg_pen = QPen(QColor("#21262d"), 10, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(
            margin, margin, rect_size, rect_size,
            30 * 16, 300 * 16,
        )

        # Score arc
        score_color = (
            QColor("#3fb950") if self._score >= 80
            else QColor("#d29922") if self._score >= 55
            else QColor("#f85149")
        )
        score_pen = QPen(score_color, 10, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(score_pen)
        span = int(300 * (self._score / 100) * 16)
        painter.drawArc(
            margin, margin, rect_size, rect_size,
            (30 + 300) * 16, -span,
        )

        # Score text
        painter.setPen(QColor("#e6edf3"))
        font = QFont("Segoe UI", 20, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self._score:.0f}")


# ─────────────────────────────────────────────────────────────────────────────
#  ENGINE CARD  (fleet list item)
# ─────────────────────────────────────────────────────────────────────────────

class EngineCard(QFrame):
    """Clickable engine summary card for fleet view."""

    clicked = Signal(str)  # engine_id

    def __init__(self, engine_id: str, score: float, n_anomalies: int,
                 top_fault: str, severity: str, parent=None):
        super().__init__(parent)
        self.setObjectName("engineCard")
        self.setCursor(Qt.PointingHandCursor)
        self._engine_id = engine_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Score dial
        dial = HealthScoreDial(score)
        layout.addWidget(dial)

        # Info
        info = QVBoxLayout()
        info.setSpacing(3)

        eid_label = QLabel(f"<b>{engine_id}</b>")
        eid_label.setObjectName("valueLabel")
        info.addWidget(eid_label)

        fault_label = QLabel(top_fault or "Anomali yok")
        fault_label.setObjectName("fieldLabel")
        fault_label.setWordWrap(True)
        info.addWidget(fault_label)

        anom_label = QLabel(f"{n_anomalies} anomali")
        anom_label.setObjectName("fieldLabel")
        info.addWidget(anom_label)

        layout.addLayout(info, stretch=1)

        # Badge
        badge = StatusBadge(severity.lower())
        layout.addWidget(badge)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._engine_id)
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  FILE PICKER ROW
# ─────────────────────────────────────────────────────────────────────────────

class FilePickerRow(QWidget):
    """Label + read-only path input + Browse button."""

    file_selected = Signal(str)

    def __init__(self, label: str, placeholder: str = "Dosya seçin…",
                 file_filter: str = "Veri Dosyaları (*.csv *.npz *.txt *.dat);;Tüm Dosyalar (*)",
                 parent=None):
        super().__init__(parent)
        self._filter = file_filter

        from PySide6.QtWidgets import QLineEdit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setObjectName("fieldLabel")
        lbl.setFixedWidth(120)
        layout.addWidget(lbl)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(placeholder)
        self._path_edit.setReadOnly(True)
        layout.addWidget(self._path_edit, stretch=1)

        btn = QPushButton("Gözat…")
        btn.setObjectName("btnBrowse")
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Dosya Seç", "", self._filter)
        if path:
            self._path_edit.setText(path)
            self.file_selected.emit(path)

    def path(self) -> str:
        return self._path_edit.text()

    def set_path(self, path: str) -> None:
        self._path_edit.setText(path)


# ─────────────────────────────────────────────────────────────────────────────
#  FOLDER PICKER ROW
# ─────────────────────────────────────────────────────────────────────────────

class FolderPickerRow(QWidget):
    folder_selected = Signal(str)

    def __init__(self, label: str, placeholder: str = "Klasör seçin…", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setObjectName("fieldLabel")
        lbl.setFixedWidth(120)
        layout.addWidget(lbl)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setReadOnly(True)
        layout.addWidget(self._edit, stretch=1)

        btn = QPushButton("Gözat…")
        btn.setObjectName("btnBrowse")
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Klasör Seç", "")
        if path:
            self._edit.setText(path)
            self.folder_selected.emit(path)

    def path(self) -> str:
        return self._edit.text()


# ─────────────────────────────────────────────────────────────────────────────
#  LOADING OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

class LoadingOverlay(QWidget):
    """Semi-transparent overlay with spinner text during analysis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setVisible(False)

        # Semi-transparent dark background
        self.setStyleSheet("background: rgba(13,17,23,200); border-radius: 8px;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._msg = QLabel("Analiz ediliyor…")
        self._msg.setAlignment(Qt.AlignCenter)
        font = QFont("Segoe UI", 14, QFont.Bold)
        self._msg.setFont(font)
        self._msg.setStyleSheet("color: #58a6ff; background: transparent;")
        layout.addWidget(self._msg)

        self._sub = QLabel("")
        self._sub.setAlignment(Qt.AlignCenter)
        self._sub.setStyleSheet("color: #8b949e; background: transparent;")
        layout.addWidget(self._sub)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate
        self._bar.setFixedWidth(280)
        layout.addWidget(self._bar, alignment=Qt.AlignCenter)

    def show_loading(self, msg: str = "Analiz ediliyor…", sub: str = "") -> None:
        self._msg.setText(msg)
        self._sub.setText(sub)
        self.setVisible(True)
        self.raise_()

    def hide_loading(self) -> None:
        self.setVisible(False)

    def resizeEvent(self, event):
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  LOG PANEL
# ─────────────────────────────────────────────────────────────────────────────

class LogPanel(QPlainTextEdit):
    """Read-only log output widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPanel")
        self.setReadOnly(True)
        self.setMaximumBlockCount(500)
        self.setPlaceholderText("Uygulama logları burada görünecek…")

    def append_log(self, msg: str, level: str = "INFO") -> None:
        colors = {
            "ERROR":   "#f85149",
            "WARNING": "#d29922",
            "INFO":    "#8b949e",
            "SUCCESS": "#3fb950",
        }
        color = colors.get(level.upper(), "#8b949e")
        self.appendHtml(f'<span style="color:{color}">{msg}</span>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ─────────────────────────────────────────────────────────────────────────────
#  MATPLOTLIB CANVAS (embed matplotlib inside Qt)
# ─────────────────────────────────────────────────────────────────────────────

class MatplotlibCanvas(QWidget):
    """Embed a matplotlib Figure inside a PySide6 widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self._canvas: Optional[FigureCanvasQTAgg] = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("Henüz grafik yok.\nAnaliz çalıştırıldıktan sonra burada görüntülenecek.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setObjectName("fieldLabel")
        self._layout.addWidget(self._placeholder)

    def set_figure(self, fig) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        # Remove old canvas
        if self._canvas:
            self._layout.removeWidget(self._canvas)
            self._canvas.deleteLater()
            self._canvas = None

        if self._placeholder:
            self._layout.removeWidget(self._placeholder)
            self._placeholder.hide()

        self._canvas = FigureCanvasQTAgg(fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout.addWidget(self._canvas)
        self._canvas.draw()

    def clear(self) -> None:
        if self._canvas:
            self._layout.removeWidget(self._canvas)
            self._canvas.deleteLater()
            self._canvas = None
        if self._placeholder:
            self._placeholder.show()
            self._layout.addWidget(self._placeholder)
