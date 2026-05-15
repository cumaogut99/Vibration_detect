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
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal, QObject
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from models import EngineRun

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
    """
    Embed a matplotlib Figure inside a PySide6 widget.

    Args:
        show_toolbar: Add a Matplotlib NavigationToolbar (pan / zoom / save).
        scrollable:   Wrap the canvas in a QScrollArea so tall figures
                      (e.g. order-comparison grids) become scrollable
                      instead of getting squished into the page.
    """

    def __init__(self, parent=None, show_toolbar: bool = False,
                 scrollable: bool = False):
        super().__init__(parent)
        self._show_toolbar = show_toolbar
        self._scrollable   = scrollable

        self._canvas = None
        self._toolbar = None
        self._figure = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        if scrollable:
            from PySide6.QtWidgets import QScrollArea
            self._scroll = QScrollArea()
            self._scroll.setWidgetResizable(False)
            self._scroll.setFrameShape(QFrame.NoFrame)
            self._scroll.setStyleSheet("background: transparent;")
            self._layout.addWidget(self._scroll, stretch=1)
        else:
            self._scroll = None

        self._install_placeholder()

    def _install_placeholder(self) -> None:
        """Yer tutucu QLabel'i (yeniden) olusturup gosterir.

        QScrollArea.setWidget ve QLayout.removeWidget cagrildiginda eski
        QLabel C++ tarafinda silinebildigi icin her seferinde yeni bir
        QLabel olusturmak en guvenlisi.
        """
        self._placeholder = QLabel(
            "Henüz grafik yok.\nAnaliz çalıştırıldıktan sonra burada görüntülenecek."
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setObjectName("fieldLabel")
        if self._scroll is not None:
            self._scroll.setWidget(self._placeholder)
        else:
            self._layout.addWidget(self._placeholder)

    def set_figure(self, fig) -> None:
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg, NavigationToolbar2QT,
        )

        # Onceki canvas + figure'i kapat → matplotlib figure sizintisi olmasin
        self._drop_canvas()
        self._drop_placeholder()

        self._figure = fig
        self._canvas = FigureCanvasQTAgg(fig)
        if self._scroll is not None:
            w, h = fig.get_size_inches()
            dpi  = fig.get_dpi()
            self._canvas.setFixedSize(int(w * dpi), int(h * dpi))
            self._scroll.setWidget(self._canvas)
        else:
            self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._layout.addWidget(self._canvas)

        if self._show_toolbar:
            self._toolbar = NavigationToolbar2QT(self._canvas, self)
            self._toolbar.setStyleSheet(
                "background:#161b22; color:#e6edf3; border:none;"
            )
            self._layout.insertWidget(0, self._toolbar)

        self._canvas.draw()

    def clear(self) -> None:
        self._drop_canvas()
        self._install_placeholder()

    def _drop_placeholder(self) -> None:
        """Placeholder QLabel'i kaldir; C++ tarafinda silinmis olabilir."""
        ph = self._placeholder
        self._placeholder = None
        if ph is None:
            return
        try:
            if self._scroll is not None and self._scroll.widget() is ph:
                self._scroll.takeWidget()
            else:
                self._layout.removeWidget(ph)
            ph.deleteLater()
        except RuntimeError:
            # Zaten silinmis (qt C++ taraf objesi yok)
            pass

    def _drop_canvas(self) -> None:
        if self._toolbar is not None:
            try:
                self._layout.removeWidget(self._toolbar)
                self._toolbar.deleteLater()
            except RuntimeError:
                pass
            self._toolbar = None
        if self._canvas is not None:
            try:
                if self._scroll is not None:
                    self._scroll.takeWidget()
                else:
                    self._layout.removeWidget(self._canvas)
                self._canvas.deleteLater()
            except RuntimeError:
                pass
            self._canvas = None
        if self._figure is not None:
            try:
                import matplotlib.pyplot as plt
                plt.close(self._figure)
            except Exception:
                pass
            self._figure = None


# ─────────────────────────────────────────────────────────────────────────────
#  WATERFALL VIEW CONTROL BAR
# ─────────────────────────────────────────────────────────────────────────────

class WaterfallControlBar(QWidget):
    """
    Hz min / Hz max / RPM min / RPM max alanlari + Yenile butonu.

    ``refresh_requested(freq_min, freq_max, rpm_min, rpm_max)`` sinyalini
    firlatir. Bos kalan alan ``None`` olarak gelir (alici varsayilan
    araligi uygulamali).
    """

    refresh_requested = Signal(object, object, object, object)

    def __init__(self, parent=None,
                 default_freq_max: float = 3000.0):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtGui import QDoubleValidator

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        v = QDoubleValidator(0.0, 1.0e6, 3, self)

        def _field(placeholder: str, width: int = 84) -> "QLineEdit":
            le = QLineEdit()
            le.setPlaceholderText(placeholder)
            le.setValidator(v)
            le.setFixedWidth(width)
            return le

        layout.addWidget(self._lbl("Hz:"))
        self._hz_min = _field("min")
        self._hz_max = _field("max")
        self._hz_max.setText(str(default_freq_max))
        layout.addWidget(self._hz_min)
        layout.addWidget(self._dash())
        layout.addWidget(self._hz_max)

        layout.addSpacing(12)
        layout.addWidget(self._lbl("RPM:"))
        self._rpm_min = _field("min")
        self._rpm_max = _field("max")
        layout.addWidget(self._rpm_min)
        layout.addWidget(self._dash())
        layout.addWidget(self._rpm_max)

        layout.addStretch()

        self._refresh_btn = QPushButton("⟳  Yenile")
        self._refresh_btn.setObjectName("btnBrowse")
        self._refresh_btn.clicked.connect(self._emit_refresh)
        layout.addWidget(self._refresh_btn)

        for le in (self._hz_min, self._hz_max, self._rpm_min, self._rpm_max):
            le.returnPressed.connect(self._emit_refresh)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    @staticmethod
    def _dash() -> QLabel:
        d = QLabel("–")
        d.setObjectName("fieldLabel")
        return d

    @staticmethod
    def _parse(le) -> Optional[float]:
        text = le.text().strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(
            self._parse(self._hz_min),
            self._parse(self._hz_max),
            self._parse(self._rpm_min),
            self._parse(self._rpm_max),
        )

    def set_rpm_range(self, rpm_min: float, rpm_max: float) -> None:
        """RPM alanlarina run'in araligini placeholder olarak yaz."""
        self._rpm_min.setPlaceholderText(f"{rpm_min:.0f}")
        self._rpm_max.setPlaceholderText(f"{rpm_max:.0f}")


# ─────────────────────────────────────────────────────────────────────────────
#  CHANNEL STORE (global olarak yuklenmis kanallari tutar)
# ─────────────────────────────────────────────────────────────────────────────

class ChannelStore(QObject):
    """Yuklenmis tum kanallari merkezi olarak yonetir.

    Anahtar formati: "<engine_id>  ·  <sensor_location>/<axis>  ·  <run_id>"
    """

    channel_added   = Signal(str, object)   # key, EngineRun
    channel_removed = Signal(str)           # key

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._channels: dict[str, EngineRun] = {}

    @staticmethod
    def make_key(run: EngineRun) -> str:
        return f"{run.engine_id}  ·  {run.sensor_location}/{run.axis}  ·  {run.run_id}"

    def add(self, run: EngineRun) -> str:
        key  = self.make_key(run)
        base = key
        n = 2
        while key in self._channels:
            key = f"{base}  (#{n})"
            n += 1
        self._channels[key] = run
        self.channel_added.emit(key, run)
        return key

    def remove(self, key: str) -> None:
        if key in self._channels:
            del self._channels[key]
            self.channel_removed.emit(key)

    def update(
        self,
        old_key: str,
        engine_id: Optional[str] = None,
        run_id: Optional[str] = None,
        sensor_location: Optional[str] = None,
        axis: Optional[str] = None,
    ) -> str:
        """Bir kanalin anahtar alanlarini gunceller.

        Anahtar alanlar (engine_id / run_id / sensor_location / axis) degisirse
        kanal eski anahtarla kaldirilip yeni anahtarla yeniden eklenir; bu
        sayede ``channel_removed`` ve ``channel_added`` sinyalleri normal yolla
        yayinlanir (DuckDB senkronizasyonu bu yolu izler).

        Yeni anahtari dondurur (degisim olmadiysa ``old_key`` ile ayni).
        """
        run = self._channels.get(old_key)
        if run is None:
            return old_key

        if engine_id is not None:
            run.engine_id = engine_id.strip() or run.engine_id
        if run_id is not None:
            run.run_id = run_id.strip() or run.run_id
        if sensor_location is not None:
            run.sensor_location = sensor_location.strip() or run.sensor_location
        if axis is not None:
            run.axis = axis.strip().upper() or run.axis

        new_key = self.make_key(run)
        if new_key == old_key:
            # Alanlar mantiksal olarak ayni — sadece varsa metadata guncelle
            return old_key

        del self._channels[old_key]
        self.channel_removed.emit(old_key)
        return self._reinsert(run)

    def _reinsert(self, run: EngineRun) -> str:
        key  = self.make_key(run)
        base = key
        n = 2
        while key in self._channels:
            key = f"{base}  (#{n})"
            n += 1
        self._channels[key] = run
        self.channel_added.emit(key, run)
        return key

    def get(self, key: str) -> Optional[EngineRun]:
        return self._channels.get(key)

    def keys(self) -> list[str]:
        return list(self._channels.keys())

    def items(self):
        return self._channels.items()

    def __len__(self) -> int:
        return len(self._channels)


# ─────────────────────────────────────────────────────────────────────────────
#  TAB BAR  (ust sekme cubugu — gorsel olarak kuvvetli)
# ─────────────────────────────────────────────────────────────────────────────

class TopTabButton(QPushButton):
    """Ust sekme cubugundaki tek bir sekme dugmesi."""

    def __init__(self, label: str, page_index: int, parent=None):
        super().__init__(label, parent)
        self.page_index = page_index
        self.setObjectName("topTabBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(False)
        self._active = False

    def setActive(self, active: bool) -> None:
        self._active = active
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# ─────────────────────────────────────────────────────────────────────────────
#  CHANNEL EDIT DIALOG  (kanal metadata duzenleme)
# ─────────────────────────────────────────────────────────────────────────────

class ChannelEditDialog(QObject):
    """Kanal metadata duzenleme dialogu icin yardimci olusturucu.

    QDialog dogrudan ``ui_widgets.py``'ye ait olmadigi icin, kucuk bir
    fonksiyon olarak sariyoruz; ``ChannelEditDialog.run(...)`` cagrilir,
    kullanici tamam ya da iptal eder; donus None ya da dict.
    """

    @staticmethod
    def run(
        parent,
        engine_id: str,
        run_id: str,
        sensor_location: str,
        axis: str,
        location_options: Optional[list] = None,
    ) -> Optional[dict]:
        """Duzenleme dialogu ac; kullanici onaylarsa yeni alanlar dict
        olarak donar (engine_id, run_id, sensor_location, axis). Iptal ya
        da hicbir alan degismediyse ``None``.

        ``location_options`` verildiyse sensor lokasyonu icin combobox
        kullanilir (waterfall kanallar); aksi halde serbest metin alani
        (FFT Max Hold kanallari).
        """
        from PySide6.QtWidgets import (
            QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
            QVBoxLayout, QLabel,
        )

        dlg = QDialog(parent)
        dlg.setWindowTitle("Kanali Duzenle")
        dlg.setModal(True)
        dlg.resize(420, 220)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        title = QLabel("Kanal metadata'sini duzenle")
        title.setObjectName("cardTitle")
        outer.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        eng_edit = QLineEdit(engine_id)
        run_edit = QLineEdit(run_id)

        if location_options:
            loc_widget = QComboBox()
            for code, name in location_options:
                loc_widget.addItem(f"{code}  —  {name}", code)
            # Mevcut degeri sec
            idx = next(
                (i for i in range(loc_widget.count())
                 if loc_widget.itemData(i) == sensor_location),
                -1,
            )
            if idx >= 0:
                loc_widget.setCurrentIndex(idx)
            else:
                loc_widget.addItem(sensor_location, sensor_location)
                loc_widget.setCurrentIndex(loc_widget.count() - 1)
        else:
            loc_widget = QLineEdit(sensor_location)

        axis_combo = QComboBox()
        axis_combo.addItems(["X", "Y", "Z"])
        idx_ax = axis_combo.findText((axis or "X").upper())
        if idx_ax >= 0:
            axis_combo.setCurrentIndex(idx_ax)

        form.addRow("Motor ID:", eng_edit)
        form.addRow("Run ID:", run_edit)
        form.addRow("Lokasyon:", loc_widget)
        form.addRow("Eksen:", axis_combo)
        outer.addLayout(form)

        bb = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Iptal")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        outer.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return None

        from PySide6.QtWidgets import QComboBox as _Cb
        if isinstance(loc_widget, _Cb):
            new_loc = loc_widget.currentData() or loc_widget.currentText().split()[0]
        else:
            new_loc = loc_widget.text().strip()

        new_eng  = eng_edit.text().strip() or engine_id
        new_run  = run_edit.text().strip() or run_id
        new_ax   = axis_combo.currentText().strip().upper() or axis

        # Hicbir alan degismediyse None don
        if (new_eng == engine_id and new_run == run_id
                and new_loc == sensor_location and new_ax == axis.upper()):
            return None

        return {
            "engine_id": new_eng,
            "run_id": new_run,
            "sensor_location": new_loc,
            "axis": new_ax,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  PYQTGRAPH TABANLI MAX HOLD GORSELLERI
#
#  Max Hold sayfasi pyqtgraph kullanir: fare ile zoom/pan, sag-tik menusu
#  (auto-range, eksen kilidi, PNG/CSV export) yerlesik gelir; ayri eksen
#  araligi input alanlarina gerek kalmaz.
# ─────────────────────────────────────────────────────────────────────────────

_PG_BG    = "#0d1117"
_PG_FG    = "#8b949e"
_PG_MEAS  = "#f0883e"
_PG_REF   = "#58a6ff"
_PG_GREEN = "#3fb950"
_PG_YEL   = "#d29922"
_PG_RED   = "#f85149"


def _spectrum_row(run: "EngineRun"):
    import numpy as np
    a = np.asarray(run.amplitudes, dtype=float)
    return a[0] if a.ndim == 2 else a


class MaxHoldSpectrumView(QWidget):
    """Olculen (+ varsa referans) max-hold spektrumu — pyqtgraph.

    Fare tekerlegi: zoom · sol-tik surukle: pan · sag-tik: menu
    (View All / X-Y kilidi / Export). Y ekseni log.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg

        pg.setConfigOptions(antialias=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(background=_PG_BG)
        self._plot.setLogMode(x=False, y=True)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("bottom", "Frekans", units="Hz",
                            color=_PG_FG)
        self._plot.setLabel("left", "Genlik (g, log)", color=_PG_FG)
        self._plot.getAxis("bottom").setPen(_PG_FG)
        self._plot.getAxis("left").setPen(_PG_FG)
        self._plot.getAxis("bottom").setTextPen(_PG_FG)
        self._plot.getAxis("left").setTextPen(_PG_FG)
        self._legend = self._plot.addLegend(offset=(-10, 10),
                                            labelTextColor=_PG_FG)
        layout.addWidget(self._plot)

        self._placeholder()

    def _placeholder(self):
        import pyqtgraph as pg
        self._plot.clear()
        ti = pg.TextItem("Kanal secip Goruntule / Karsilastir calistirin.",
                         color=_PG_FG, anchor=(0.5, 0.5))
        ti.setPos(0.5, 0.5)
        self._plot.addItem(ti)

    def set_data(self, meas_run, ref_run=None) -> None:
        import numpy as np
        self._plot.clear()
        if self._legend is not None:
            self._legend.clear()

        mf = np.asarray(meas_run.frequencies, dtype=float)
        ma = np.clip(_spectrum_row(meas_run), 1e-9, None)
        self._plot.plot(
            mf, ma, pen={"color": _PG_MEAS, "width": 1},
            name=f"Olculen: {meas_run.engine_id} · {meas_run.sensor_location}",
        )
        if ref_run is not None:
            rf = np.asarray(ref_run.frequencies, dtype=float)
            ra = np.clip(_spectrum_row(ref_run), 1e-9, None)
            self._plot.plot(
                rf, ra, pen={"color": _PG_REF, "width": 1},
                name=f"Referans: {ref_run.engine_id} · {ref_run.sensor_location}",
            )
        self._plot.enableAutoRange()
        self._plot.autoRange()


class MaxHoldRatioView(QWidget):
    """Order bant-maks oran cubuk grafigi — pyqtgraph.

    ``set_bands`` ``analysis.MaxHoldAnalyzer.analyze`` ikinci donus
    degerini (order -> MaxHoldBand) alir.
    """

    WARN, CRIT = 1.5, 2.5

    def __init__(self, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget(background=_PG_BG)
        self._plot.showGrid(x=False, y=True, alpha=0.25)
        self._plot.setLabel("left", "Bant-maks oran (olculen / referans)",
                            color=_PG_FG)
        self._plot.setLabel("bottom", "Order", color=_PG_FG)
        self._plot.getAxis("bottom").setPen(_PG_FG)
        self._plot.getAxis("left").setPen(_PG_FG)
        self._plot.getAxis("bottom").setTextPen(_PG_FG)
        self._plot.getAxis("left").setTextPen(_PG_FG)
        layout.addWidget(self._plot)

    def set_bands(self, bands: dict) -> None:
        import numpy as np
        import pyqtgraph as pg

        self._plot.clear()
        items = sorted(
            ((o, b) for o, b in bands.items()
             if getattr(b, "ratio", None) is not None),
            key=lambda kv: kv[0],
        )
        if not items:
            ti = pg.TextItem("Ortak order bandi yok.", color=_PG_FG,
                             anchor=(0.5, 0.5))
            self._plot.addItem(ti)
            return

        orders = [o for o, _ in items]
        ratios = [float(b.ratio) for _, b in items]
        x = np.arange(len(orders))

        for xi, r in zip(x, ratios):
            c = (_PG_RED if r >= self.CRIT
                 else _PG_YEL if r >= self.WARN
                 else _PG_GREEN)
            bg = pg.BarGraphItem(x=[xi], height=[r], width=0.7, brush=c, pen=c)
            self._plot.addItem(bg)

        for y, col, dash in (
            (1.0, _PG_FG, [2, 4]),
            (self.WARN, _PG_YEL, [6, 4]),
            (self.CRIT, _PG_RED, [6, 4]),
        ):
            line = pg.InfiniteLine(
                pos=y, angle=0,
                pen=pg.mkPen(color=col, width=1, dash=dash),
            )
            self._plot.addItem(line)

        ax = self._plot.getAxis("bottom")
        ax.setTicks([[(int(xi), f"{o:g}×") for xi, o in zip(x, orders)]])
        self._plot.enableAutoRange()
        self._plot.autoRange()
