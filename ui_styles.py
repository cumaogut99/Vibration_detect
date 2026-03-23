"""
ui_styles.py — Tüm QSS stilleri ve renk paleti.
Tek yerden yönetilen koyu endüstriyel tema.
"""

PALETTE_COLORS = {
    "bg":          "#0d1117",
    "surface":     "#161b22",
    "surface_alt": "#1c2128",
    "surface_hover": "#21262d",
    "border":      "#30363d",
    "border_focus":"#58a6ff",
    "text":        "#e6edf3",
    "muted":       "#8b949e",
    "accent":      "#58a6ff",
    "accent_dark": "#1f6feb",
    "green":       "#3fb950",
    "yellow":      "#d29922",
    "red":         "#f85149",
    "orange":      "#f0883e",
    "purple":      "#bc8cff",
}

STYLESHEET = """
/* ─── Global ─────────────────────────────────────────────── */
* {
    font-family: "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #e6edf3;
}

QMainWindow, QWidget {
    background-color: #0d1117;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #161b22;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #58a6ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #161b22;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #58a6ff; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ─── Sidebar ─────────────────────────────────────────────── */
QWidget#sidebar {
    background-color: #0d1117;
    border-right: 1px solid #21262d;
}

QFrame#sidebarTitle {
    background-color: #0d1117;
}

QLabel#logoLabel {
    font-size: 16px;
    font-weight: 700;
    color: #58a6ff;
    letter-spacing: 0.5px;
}

QLabel#logoSub {
    font-size: 10px;
    color: #8b949e;
    letter-spacing: 0.3px;
}

QLabel#navSection {
    font-size: 10px;
    font-weight: 600;
    color: #8b949e;
    letter-spacing: 1.2px;
    padding: 10px 0 4px 0;
}

QLabel#sidebarVer {
    font-size: 10px;
    color: #30363d;
}

/* ─── Nav Buttons ─────────────────────────────────────────── */
QPushButton#navBtn {
    background: transparent;
    border: none;
    border-radius: 0;
    text-align: left;
    padding: 10px 20px;
    font-size: 13px;
    color: #8b949e;
    border-left: 3px solid transparent;
}
QPushButton#navBtn:hover {
    background: #161b22;
    color: #e6edf3;
}
QPushButton#navBtn[active="true"] {
    background: #161b22;
    color: #58a6ff;
    border-left: 3px solid #58a6ff;
    font-weight: 600;
}

/* ─── Content Pages ───────────────────────────────────────── */
QWidget#pageContent {
    background: #0d1117;
}

/* ─── Page Header ─────────────────────────────────────────── */
QLabel#pageTitle {
    font-size: 20px;
    font-weight: 700;
    color: #e6edf3;
    letter-spacing: 0.3px;
}

QLabel#pageSubtitle {
    font-size: 12px;
    color: #8b949e;
}

/* ─── Cards / Panels ──────────────────────────────────────── */
QFrame#card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
}

QFrame#cardHeader {
    background: #1c2128;
    border-radius: 8px 8px 0 0;
    border-bottom: 1px solid #30363d;
}

QLabel#cardTitle {
    font-size: 13px;
    font-weight: 600;
    color: #e6edf3;
    padding: 10px 16px;
}

/* ─── Section Title ───────────────────────────────────────── */
QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 600;
    color: #8b949e;
    letter-spacing: 0.8px;
    padding-bottom: 6px;
}

/* ─── Inputs ──────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 10px;
    color: #e6edf3;
    font-size: 13px;
    min-height: 32px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #58a6ff;
    background: #1c2128;
}
QLineEdit:read-only {
    color: #8b949e;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8b949e;
}
QComboBox QAbstractItemView {
    background: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    color: #e6edf3;
    outline: none;
}

/* ─── Buttons ─────────────────────────────────────────────── */
QPushButton {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 16px;
    color: #e6edf3;
    font-size: 13px;
    min-height: 32px;
}
QPushButton:hover {
    background: #30363d;
    border-color: #8b949e;
}
QPushButton:pressed {
    background: #161b22;
}
QPushButton:disabled {
    color: #484f58;
    border-color: #21262d;
    background: #161b22;
}

QPushButton#btnPrimary {
    background: #1f6feb;
    border: 1px solid #388bfd;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#btnPrimary:hover {
    background: #388bfd;
}
QPushButton#btnPrimary:pressed {
    background: #1158c7;
}
QPushButton#btnPrimary:disabled {
    background: #21262d;
    border-color: #30363d;
    color: #484f58;
}

QPushButton#btnSuccess {
    background: #196c2e;
    border: 1px solid #2ea043;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#btnSuccess:hover { background: #2ea043; }

QPushButton#btnDanger {
    background: #6e1b1b;
    border: 1px solid #f85149;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#btnBrowse {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 12px;
    color: #8b949e;
    min-width: 80px;
}
QPushButton#btnBrowse:hover {
    color: #58a6ff;
    border-color: #58a6ff;
}

/* ─── Labels ──────────────────────────────────────────────── */
QLabel#fieldLabel {
    font-size: 12px;
    color: #8b949e;
    font-weight: 500;
}

QLabel#valueLabel {
    font-size: 13px;
    color: #e6edf3;
}

/* ─── Tables ──────────────────────────────────────────────── */
QTableWidget {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    gridline-color: #21262d;
    selection-background-color: #1f6feb;
    alternate-background-color: #1c2128;
}
QTableWidget::item {
    padding: 6px 10px;
    border: none;
}
QHeaderView::section {
    background: #21262d;
    color: #8b949e;
    font-size: 11px;
    font-weight: 600;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid #30363d;
    letter-spacing: 0.5px;
}
QHeaderView::section:first { border-radius: 6px 0 0 0; }
QHeaderView::section:last  { border-radius: 0 6px 0 0; }

/* ─── TabWidget ───────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 0 6px 6px 6px;
    background: #161b22;
}
QTabBar::tab {
    background: #0d1117;
    border: 1px solid #30363d;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 8px 16px;
    color: #8b949e;
    margin-right: 2px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #161b22;
    color: #58a6ff;
    border-top: 2px solid #58a6ff;
}
QTabBar::tab:hover:!selected {
    background: #1c2128;
    color: #e6edf3;
}

/* ─── Progress Bar ────────────────────────────────────────── */
QProgressBar {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1f6feb, stop:1 #58a6ff);
    border-radius: 4px;
}

/* ─── Status Bar ──────────────────────────────────────────── */
QStatusBar#statusBar {
    background: #161b22;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-size: 11px;
    padding: 4px 12px;
}

/* ─── Log Panel ───────────────────────────────────────────── */
QPlainTextEdit#logPanel {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    color: #8b949e;
    font-family: "Consolas", "JetBrains Mono", "Fira Code", monospace;
    font-size: 11px;
    padding: 8px;
}

/* ─── Divider ─────────────────────────────────────────────── */
QFrame#divider {
    background: #21262d;
    max-height: 1px;
    border: none;
}

/* ─── Score Badges ────────────────────────────────────────── */
QLabel#badgeCritical {
    background: #6e1b1b;
    color: #f85149;
    border: 1px solid #f85149;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#badgeWarning {
    background: #4d3800;
    color: #d29922;
    border: 1px solid #d29922;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#badgeOk {
    background: #0f3320;
    color: #3fb950;
    border: 1px solid #3fb950;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}

/* ─── Engine Card ─────────────────────────────────────────── */
QFrame#engineCard {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
}
QFrame#engineCard:hover {
    border-color: #58a6ff;
}

/* ─── Tooltip ─────────────────────────────────────────────── */
QToolTip {
    background: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
}

/* ─── CheckBox ────────────────────────────────────────────── */
QCheckBox {
    color: #e6edf3;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background: #161b22;
}
QCheckBox::indicator:checked {
    background: #1f6feb;
    border-color: #58a6ff;
}
"""
