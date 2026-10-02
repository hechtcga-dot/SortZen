"""Colours, fonts and the Qt style sheet."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

FONT_DIR = Path(__file__).resolve().parent / "fonts"
ASSET_DIR = Path(__file__).resolve().parent / "assets"

GROUND = "#EFECE5"
PANEL = "#FBFAF7"
WHITE = "#FFFFFF"
LINE = "#DCD7CC"
LINE_SOFT = "#E2DDD2"
INK = "#1F2421"
INK_2 = "#3F433E"
MUTED = "#5E625C"
ACCENT = "#2E6A4C"
ACCENT_DARK = "#1F4B35"
ACCENT_HOVER = "#245A40"
ACCENT_TINT = "#E3EFE7"
WARN_TEXT = "#8A4F06"
WARN_BG = "#FBEBD2"
DANGER_TEXT = "#8A2E1C"
DANGER_BG = "#F6E3DE"
INFO_TEXT = "#2B4A6B"
INFO_BG = "#E4EAF2"
NEUTRAL_BG = "#EEEAE2"
TAB_STRIP = "#E2DED4"

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"
SERIF = "Fraunces"


def load_fonts() -> None:
    for ttf in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))


def font(size=10, weight=QFont.Weight.Normal, family=SANS) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono(size=10, weight=QFont.Weight.Normal) -> QFont:
    f = font(size, weight, MONO)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(GROUND))
    p.setColor(QPalette.ColorRole.Base, QColor(WHITE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL))
    p.setColor(QPalette.ColorRole.Text, QColor(INK))
    p.setColor(QPalette.ColorRole.WindowText, QColor(INK))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(INK))
    p.setColor(QPalette.ColorRole.Button, QColor(WHITE))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_TINT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(INK))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(INK))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(WHITE))
    return p


STYLE = f"""
* {{ font-family: "{SANS}"; color: {INK}; }}
QMainWindow, QWidget#ground {{ background: {GROUND}; }}
QToolTip {{ background: {INK}; color: {WHITE}; border: none; padding: 4px 6px; }}

QFrame#header {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QFrame#toolbar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QFrame#vsep {{ background: {LINE}; max-width: 1px; min-width: 1px; }}
QLabel#muted, QLabel#hint {{ color: {MUTED}; }}
QLabel#hint {{ font-size: 8.5pt; }}
QLabel#versionPill {{ background: {NEUTRAL_BG}; color: {MUTED}; border-radius: 4px; padding: 1px 6px;
    font-family: "{MONO}"; font-size: 8pt; }}
QLabel#sectionCaps {{ color: {MUTED}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#pageTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#cardTitle {{ font-weight: 600; font-size: 10.5pt; }}

QPushButton {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: #BDB6A6; background: #FAF9F6; }}
QPushButton:pressed {{ background: {NEUTRAL_BG}; }}
QPushButton:disabled {{ color: #A7AAA4; border-color: {LINE_SOFT}; background: #F6F4EF; }}
QPushButton#primary {{ background: {ACCENT}; color: {WHITE}; border: 1px solid {ACCENT_DARK}; font-weight: 600; padding: 7px 16px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #9DB8A8; border-color: #9DB8A8; color: #F2F6F3; }}
QPushButton#strong {{ font-weight: 600; padding: 7px 14px; }}
QPushButton#iconButton {{ border: 1px solid transparent; background: transparent; padding: 4px; }}
QPushButton#iconButton:hover {{ border-color: {LINE}; background: {WHITE}; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px; text-align: left; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#menuButton {{ border: none; background: transparent; padding: 2px 4px; }}
QPushButton#menuButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {WHITE}; border: 1px solid {LINE}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {ACCENT_TINT}; selection-color: {INK}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:read-only {{ background: #F6F4EF; color: {INK_2}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{(ASSET_DIR / 'chevron-down.svg').as_posix()}"); width: 10px; height: 10px; }}
QSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 22px; border-left: 1px solid {LINE}; background: {PANEL}; }}
QSpinBox::up-button {{ border-top-right-radius: 6px; }}
QSpinBox::down-button {{ border-bottom-right-radius: 6px; border-top: 1px solid {LINE}; }}
QSpinBox::up-arrow {{ image: url("{(ASSET_DIR / 'chevron-up.svg').as_posix()}"); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url("{(ASSET_DIR / 'chevron-down.svg').as_posix()}"); width: 9px; height: 9px; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}

QFrame#tree {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QTreeWidget {{ background: {PANEL}; border: none; outline: 0; }}
QTreeWidget::item {{ padding: 2px 2px; border-radius: 4px; }}
QTreeWidget::item:selected {{ background: {ACCENT_TINT}; color: {INK}; }}
QTreeWidget::item:hover {{ background: #F1EEE7; }}
QLabel#treeFooter {{ color: {MUTED}; font-size: 8.5pt; border: 1px dashed {LINE}; border-radius: 8px; padding: 8px; }}

QTabWidget::pane {{ border: none; background: {GROUND}; }}
QTabWidget::tab-bar {{ left: 0; }}
QTabBar {{ background: {TAB_STRIP}; }}
QTabBar::tab {{ background: transparent; border: none; border-right: 1px solid {LINE};
    min-width: 90px; max-width: 200px; height: 22px; padding: 7px 8px 7px 12px; margin-top: 6px; color: {INK_2}; text-align: left; }}
QTabBar::tab:first {{ margin-left: 8px; }}
QTabBar::tab:selected {{ background: {GROUND}; border-right-color: transparent; color: {INK}; font-weight: 600;
    border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QTabBar::tab:hover:!selected {{ background: #EAE6DE; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QTabBar::close-button {{ subcontrol-position: right; margin-left: 4px; }}
QToolButton#tabClose {{ border: none; border-radius: 10px; background: transparent; padding: 0; }}
QToolButton#tabClose:hover {{ background: {NEUTRAL_BG}; }}
QToolButton#tabClose:pressed {{ background: {LINE}; }}

QFrame#card {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 10px; }}
QProgressBar {{ background: {LINE_SOFT}; border: none; border-radius: 4px; height: 8px; max-height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QTableView {{ background: {WHITE}; border: none; gridline-color: transparent; outline: 0;
    selection-background-color: {ACCENT_TINT}; selection-color: {INK}; alternate-background-color: #FCFBF8; }}
QHeaderView::section {{ background: {WHITE}; border: none; border-bottom: 1px solid {LINE};
    color: {MUTED}; font-size: 8.5pt; font-weight: 600; padding: 6px 8px; }}
QTableView QHeaderView::section {{ padding-right: 18px; }}
QHeaderView::up-arrow, QHeaderView::down-arrow {{ subcontrol-origin: padding; subcontrol-position: center right;
    width: 9px; height: 9px; right: 5px; }}
QHeaderView::up-arrow {{ image: url("{(ASSET_DIR / 'chevron-up.svg').as_posix()}"); }}
QHeaderView::down-arrow {{ image: url("{(ASSET_DIR / 'chevron-down.svg').as_posix()}"); }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C9C3B6; border-radius: 4px; min-height: 28px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C9C3B6; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {LINE}; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; padding: 2px 6px; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {ACCENT_TINT}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QMenu {{ background: {WHITE}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_TINT}; color: {INK}; }}
QMenu::separator {{ height: 1px; background: {LINE_SOFT}; margin: 4px 6px; }}
QLabel#fieldLabel {{ font-size: 9pt; font-weight: 600; color: {INK_2}; }}QLabel#appName {{ font-family: "{SERIF}"; font-size: 14pt; font-weight: 600; color: {ACCENT_DARK}; }}
QLabel#stepNumber {{ background: {ACCENT_TINT}; color: {ACCENT_DARK}; border-radius: 12px; font-weight: 600;
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; qproperty-alignment: AlignCenter; }}
"""
