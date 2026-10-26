"""Interface theme — colour palettes and the style sheet.

Design language: neutral, layered, card-based. The neutrals are true greys and
there is ONE accent colour. No gradients, no bright or neon colours, no multiple
accents — the aim is a calm, professional tool.

The program applies its own theme, so it looks the same on every computer
regardless of the operating system's light or dark setting.

The theme is built from two independent parts:

  BASE    : neutral surfaces, text and status colours for light and dark mode.
  ACCENTS : the colour palette the user picks — accent and sidebar tones.

Mode and palette are chosen independently: 2 modes x 4 palettes = 8 looks,
all produced from one colour dictionary.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

BASE = {
    "light": {
        # Text colours are deliberately DARK: every tone gives at least 4.5:1
        # contrast on white.
        "window": "#eceff3",
        "card": "#ffffff",
        "card_alt": "#f5f7fa",
        "border": "#d5dbe3",
        "border_strong": "#b4bdc8",
        "text": "#111820",
        "text_muted": "#3f4a57",
        "text_faint": "#5b6674",
        # status colours (feedback, not accents; they do not follow the palette)
        "success": "#15803d",
        "success_soft": "#e9f7ee",
        "warning": "#a45309",
        "warning_soft": "#fdf3e6",
        "error": "#b3261e",
        "error_soft": "#fdeceb",
        "sidebar_text": "#c8d3d8",
        "sidebar_text_active": "#ffffff",
    },
    "dark": {
        # Dark surfaces; text is off-white (pure white on dark tires the eye).
        "window": "#0f1417",
        "card": "#182126",
        "card_alt": "#131b1f",
        "border": "#2b373d",
        "border_strong": "#3c4a52",
        "text": "#eef3f5",
        "text_muted": "#b3c0c7",
        "text_faint": "#8d9ba3",
        "success": "#4ade80",
        "success_soft": "#14301f",
        "warning": "#fbbf24",
        "warning_soft": "#33260d",
        "error": "#f87171",
        "error_soft": "#361a19",
        "sidebar_text": "#aebac1",
        "sidebar_text_active": "#ffffff",
    },
}

# Colour palettes. Dark tones are deliberately LIGHTER: a light-mode accent is
# unreadable on a dark surface.
ACCENTS = {
    "teal": {
        "name": "Teal",
        "light": {
            "accent": "#0f766e", "accent_dark": "#0a5a54", "accent_bright": "#14a098",
            "accent_soft": "#e2f4f1", "accent_border": "#a8d8d1",
            "sidebar_bg": "#132025", "sidebar_bg_deep": "#0d171b", "sidebar_active": "#1e3239",
        },
        "dark": {
            "accent": "#2bb3a3", "accent_dark": "#1f8d81", "accent_bright": "#3fd0be",
            "accent_soft": "#16302e", "accent_border": "#2a5a55",
            "sidebar_bg": "#0b1114", "sidebar_bg_deep": "#070c0e", "sidebar_active": "#18262c",
        },
    },
    "indigo": {
        "name": "Indigo",
        "light": {
            "accent": "#1d4ed8", "accent_dark": "#1739a8", "accent_bright": "#3b6ef6",
            "accent_soft": "#e8eefc", "accent_border": "#b9caf6",
            "sidebar_bg": "#141c2e", "sidebar_bg_deep": "#0d1320", "sidebar_active": "#212e4a",
        },
        "dark": {
            "accent": "#6ea0ff", "accent_dark": "#4a79d8", "accent_bright": "#8fb6ff",
            "accent_soft": "#16203a", "accent_border": "#2c4270",
            "sidebar_bg": "#0a0f1a", "sidebar_bg_deep": "#070b13", "sidebar_active": "#172038",
        },
    },
    "slate": {
        "name": "Slate",
        "light": {
            "accent": "#41505e", "accent_dark": "#2d3944", "accent_bright": "#5b6e7e",
            "accent_soft": "#eceff2", "accent_border": "#c2cbd4",
            "sidebar_bg": "#1a1f24", "sidebar_bg_deep": "#12161a", "sidebar_active": "#2a323a",
        },
        "dark": {
            "accent": "#9fb2c2", "accent_dark": "#78899a", "accent_bright": "#c3d2de",
            "accent_soft": "#1e262c", "accent_border": "#3b4750",
            "sidebar_bg": "#0d1113", "sidebar_bg_deep": "#090c0e", "sidebar_active": "#1b2226",
        },
    },
    "maroon": {
        "name": "Maroon",
        "light": {
            "accent": "#9f1239", "accent_dark": "#7c0f2d", "accent_bright": "#c81e4e",
            "accent_soft": "#fcebf0", "accent_border": "#f0bfcb",
            "sidebar_bg": "#241419", "sidebar_bg_deep": "#190d11", "sidebar_active": "#3a2028",
        },
        "dark": {
            "accent": "#f0728f", "accent_dark": "#c24a68", "accent_bright": "#ff93aa",
            "accent_soft": "#33141d", "accent_border": "#66293a",
            "sidebar_bg": "#150a0d", "sidebar_bg_deep": "#0e0609", "sidebar_active": "#2a1319",
        },
    },
}

MODES = ("light", "dark")
DEFAULT_MODE = "light"
DEFAULT_ACCENT = "teal"


def build_colours(mode_name: str, accent_name: str) -> dict:
    mode_name = mode_name if mode_name in BASE else DEFAULT_MODE
    accent_name = accent_name if accent_name in ACCENTS else DEFAULT_ACCENT
    return {**BASE[mode_name], **ACCENTS[accent_name][mode_name]}


def accents() -> list[tuple[str, str]]:
    """[(key, display name)] for the palette picker."""
    return [(key, value["name"]) for key, value in ACCENTS.items()]


# Active colours. Other modules read from here (theme.COLOURS["accent"]); the
# dictionary is updated IN PLACE when the theme changes, so references stay valid.
COLOURS = build_colours(DEFAULT_MODE, DEFAULT_ACCENT)
_mode = DEFAULT_MODE
_accent = DEFAULT_ACCENT


def _write_icon(name: str, svg: str) -> str:
    """Write a small SVG icon to a temporary folder for use in the style sheet.

    Qt style sheets do not reliably accept data URIs in ``image:``; a real file
    path is needed. Icons are generated at run time, so nothing extra has to be
    bundled with the executable.
    """
    folder = Path(tempfile.gettempdir()) / "DocFiller-icons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(svg, encoding="utf-8")
    return path.as_posix()  # style sheets expect forward slashes


_TICK = _write_icon(
    "tick.svg",
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">'
    '<path d="M2.5 7.5 L5.5 10.5 L11.5 3.5" stroke="#ffffff" stroke-width="2.2" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
)


def _arrow_icon() -> str:
    return _write_icon(
        "arrow.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
        f'<path d="M2.5 4.5 L6 8 L9.5 4.5" stroke="{COLOURS["text_muted"]}" stroke-width="1.6" '
        'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    )


_ARROW = _arrow_icon()


def _build_style() -> str:
    c = COLOURS
    return f"""
QWidget {{
    background: {c["window"]};
    color: {c["text"]};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {c["window"]};
    border: none;
}}

/* ---- Card-like sections ---- */
QGroupBox {{
    background: {c["card"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
    margin-top: 15px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 4px 12px;
    color: #ffffff;
    background: {c["accent"]};
    border: none;
    border-radius: 6px;
    font-size: 8.5pt;
    font-weight: 800;
}}

/* ---- Sidebar ---- */
QFrame#sidebar {{
    background: {c["sidebar_bg"]};
    border: none;
}}
/* Containers inside the sidebar must not paint their own background: the
   general "QWidget" rule would give them the light window colour and show a
   light strip on the dark sidebar. */
QFrame#sidebar > QWidget {{
    background: transparent;
}}
QFrame#sidebar QLabel {{
    background: transparent;
    color: {c["sidebar_text"]};
}}
/* Selectors here must be MORE specific than "QFrame#sidebar QLabel", otherwise
   that rule wins and the title looks faded. */
QFrame#sidebar QLabel#sidebarNote {{
    color: {c["sidebar_text"]};
    background: transparent;
}}
QPushButton#sidebarItem {{
    background: transparent;
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0;
    color: {c["sidebar_text"]};
    padding: 13px 18px;
    text-align: left;
    font-size: 10pt;
    font-weight: 600;
}}
QPushButton#sidebarItem:hover {{
    background: {c["sidebar_active"]};
    color: {c["sidebar_text_active"]};
}}
QPushButton#sidebarItem:checked {{
    background: {c["sidebar_active"]};
    border-left: 4px solid {c["accent_bright"]};
    color: {c["sidebar_text_active"]};
}}

/* ---- Inputs ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {c["card"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {c["accent"]};
    selection-color: #ffffff;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {c["accent"]};
    padding: 6px 9px;
}}
QLineEdit:hover, QComboBox:hover {{
    border-color: {c["accent"]};
}}
QLineEdit[missing="true"] {{
    background: {c["warning_soft"]};
    border-color: #e0c39a;
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: url({_ARROW});
    width: 12px;
    height: 12px;
    margin-right: 10px;
}}
/* Dropdown lists. "color" MUST be stated: otherwise the list inherits the
   box's text colour, and a white-text box in the dark sidebar produces white
   text on a white list. */
QComboBox QAbstractItemView {{
    background: {c["card"]};
    color: {c["text"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    selection-background-color: {c["accent"]};
    selection-color: #ffffff;
    padding: 4px;
    outline: 0;
}}
/* NO padding or min-height on items. Style-sheet padding does not change the
   view's row step (the delegate's sizeHint): rows are drawn 34 px tall but
   placed 17 px apart, and they OVERLAP. Row height comes from code instead
   (see style_dropdown). */
QComboBox QAbstractItemView::item {{
    color: {c["text"]};
    background: transparent;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {c["accent_soft"]};
    color: {c["accent_dark"]};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {c["accent"]};
    color: #ffffff;
}}

/* ---- Buttons ---- */
QPushButton {{
    background: {c["card"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    color: {c["text"]};
}}
QPushButton:hover {{
    background: {c["accent_soft"]};
    border-color: {c["accent"]};
    color: {c["accent_dark"]};
}}
QPushButton:pressed {{
    background: {c["accent_border"]};
}}
QPushButton:disabled {{
    background: {c["card_alt"]};
    color: {c["text_faint"]};
    border-color: {c["border"]};
}}
QPushButton#primary {{
    background: {c["accent"]};
    color: #ffffff;
    border: none;
    padding: 13px 20px;
    font-size: 10.5pt;
    font-weight: 700;
}}
QPushButton#primary:hover {{ background: {c["accent_dark"]}; }}
QPushButton#primary:disabled {{ background: {c["border_strong"]}; color: #ffffff; }}
QPushButton#small {{
    padding: 4px 10px;
    font-size: 9pt;
    font-weight: 500;
    color: {c["text_muted"]};
}}
/* Section heading inside form windows, shown as written in the document */
QLabel#sectionHeading {{
    color: {c["accent_dark"]};
    background: {c["accent_soft"]};
    border: none;
    border-left: 3px solid {c["accent"]};
    border-radius: 4px;
    padding: 7px 10px;
    font-weight: 700;
    font-size: 10pt;
    margin-top: 6px;
}}

/* Arrow of the memory input that lists earlier values */
QToolButton#memoryArrow {{
    background: {c["card_alt"]};
    border: 1px solid {c["border"]};
    border-left: none;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    color: {c["text_muted"]};
    padding: 0 8px;
    min-height: 30px;
    font-size: 11pt;
}}
QToolButton#memoryArrow:hover:enabled {{
    background: {c["accent_soft"]};
    color: {c["accent_dark"]};
}}
QToolButton#memoryArrow:disabled {{ color: {c["border"]}; }}

/* Account card in the sidebar */
QFrame#accountCard {{
    background: {c["sidebar_active"]};
    border: none;
    border-top: 1px solid {c["sidebar_bg"]};
    border-bottom: 1px solid {c["sidebar_bg"]};
}}
QFrame#accountCard QLabel#accountBadge {{
    background: {c["accent"]};
    color: #ffffff;
    border-radius: 15px;
    font-weight: 800;
    font-size: 10pt;
}}
QFrame#accountCard QLabel#accountName {{
    color: {c["sidebar_text_active"]};
    font-weight: 700;
    font-size: 9.5pt;
}}
QFrame#accountCard QLabel#accountRole {{
    color: {c["sidebar_text"]};
    font-size: 8pt;
}}

/* Brand header of the sign-in window */
QFrame#signInHeader {{
    background: {c["sidebar_bg"]};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

/* Group headings and small buttons in the sidebar */
QFrame#sidebar QLabel#sidebarGroup {{
    color: {c["sidebar_text"]};
    font-size: 7.5pt;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 14px 18px 4px 18px;
    background: transparent;
}}
QFrame#sidebar QPushButton#sidebarButton, QFrame#accountCard QPushButton#sidebarButton {{
    background: {c["sidebar_active"]};
    color: {c["sidebar_text_active"]};
    border: 1px solid {c["sidebar_bg_deep"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 8.5pt;
    font-weight: 600;
    text-align: center;
}}
QFrame#sidebar QPushButton#sidebarButton:hover, QFrame#accountCard QPushButton#sidebarButton:hover {{
    background: {c["accent"]};
    border-color: {c["accent_bright"]};
}}

/* Dropdowns in the sidebar (palette, language) */
QFrame#accountCard QComboBox#sidebarSelect {{
    background: {c["sidebar_active"]};
    color: {c["sidebar_text_active"]};
    border: 1px solid {c["sidebar_bg_deep"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 8.5pt;
    font-weight: 600;
    min-height: 18px;
}}
QFrame#accountCard QComboBox#sidebarSelect:hover {{ border-color: {c["accent_bright"]}; }}
QFrame#accountCard QComboBox#sidebarSelect::drop-down {{ border: none; width: 18px; }}

QPushButton#link {{
    background: transparent;
    border: none;
    color: {c["accent"]};
    padding: 3px 6px;
    text-decoration: underline;
    font-weight: 600;
}}
QPushButton#link:hover {{ color: {c["accent_dark"]}; background: transparent; }}

/* ---- Check boxes ---- */
QCheckBox {{
    padding: 5px 2px;
    spacing: 9px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {c["border_strong"]};
    border-radius: 4px;
    background: {c["card"]};
}}
QCheckBox::indicator:hover {{ border-color: {c["accent"]}; }}
QCheckBox::indicator:checked {{
    background: {c["accent"]};
    border-color: {c["accent"]};
    image: url({_TICK});
}}
QCheckBox::indicator:disabled {{ background: {c["card_alt"]}; border-color: {c["border"]}; }}
QCheckBox:disabled {{ color: {c["text_faint"]}; }}

/* ---- Dialogs ---- */
QDialog {{
    background: {c["window"]};
}}
QDialog QFrame#dialogHeader {{
    background: {c["card"]};
    border-bottom: 1px solid {c["border"]};
}}
QDialog QFrame#dialogFooter {{
    background: {c["card"]};
    border-top: 1px solid {c["border"]};
}}

/* ---- Lists ---- */
QListWidget {{
    background: {c["card"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 10px 12px;
    border-radius: 6px;
    color: {c["text"]};
}}
QListWidget::item:hover {{ background: {c["accent_soft"]}; }}
QListWidget::item:selected {{
    background: {c["accent_soft"]};
    color: {c["text"]};
    border: 1px solid {c["accent_border"]};
}}

/* ---- Tables ---- */
QTableWidget {{
    background: {c["card"]};
    alternate-background-color: {c["card_alt"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    gridline-color: {c["border"]};
    selection-background-color: {c["accent_soft"]};
    selection-color: {c["text"]};
    outline: none;
}}
QTableWidget::item {{
    padding: 7px 10px;
    border: none;
    color: {c["text"]};
}}
QTableWidget::item:selected {{
    background: {c["accent_soft"]};
    color: {c["text"]};
}}
QHeaderView::section {{
    background: {c["accent"]};
    color: #ffffff;
    padding: 9px 10px;
    border: none;
    border-right: 1px solid {c["accent_dark"]};
    font-weight: 700;
    font-size: 9pt;
}}
QHeaderView::section:last {{ border-right: none; }}
QTableCornerButton::section {{ background: {c["accent"]}; border: none; }}

/* ---- Text boxes ---- */
QTextEdit {{
    background: {c["card_alt"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 10px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 9pt;
}}

/* ---- Progress ---- */
QProgressBar {{
    background: {c["border"]};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {c["accent"]};
    border-radius: 3px;
}}

/* ---- Scroll bars ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c["border_strong"]};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c["text_faint"]}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c["border_strong"]};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {c["card"]};
    color: {c["text"]};
    border: 1px solid {c["border_strong"]};
    padding: 5px;
}}
"""


STYLE = _build_style()


def mode() -> str:
    return _mode


def accent() -> str:
    return _accent


def set_theme(mode_name: str | None = None, accent_name: str | None = None) -> str:
    """Change the mode and/or palette.

    The colour dictionary is updated IN PLACE, so code holding a reference to
    ``theme.COLOURS`` never looks at stale colours. The style sheet is rebuilt;
    windows created afterwards use it, and refreshing open windows is the
    caller's job (see main_window.MainWindow.rebuild).
    """
    global STYLE, _mode, _accent, _ARROW
    if mode_name is not None and mode_name not in BASE:
        mode_name = None
    if accent_name is not None and accent_name not in ACCENTS:
        accent_name = None
    _mode = mode_name or _mode
    _accent = accent_name or _accent
    COLOURS.clear()
    COLOURS.update(build_colours(_mode, _accent))
    # The dropdown arrow embeds a palette colour, so it is written again.
    _ARROW = _arrow_icon()
    STYLE = _build_style()
    return _mode


def _popup_style() -> str:
    """Style for a dropdown's own popup list.

    The popup is a SEPARATE top-level window and, in the Fusion style, draws its
    item text from the application palette. The general style sheet does not
    reach it, so the list could inherit a white text colour and become
    invisible on a white background. This style is set on the view directly.
    """
    c = COLOURS
    return f"""
QListView {{
    background: {c["card"]};
    color: {c["text"]};
    border: 1px solid {c["border_strong"]};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}
QListView::item {{
    color: {c["text"]};
    background: transparent;
    border-radius: 4px;
}}
QListView::item:hover {{
    background: {c["accent_soft"]};
    color: {c["accent_dark"]};
}}
QListView::item:selected {{
    background: {c["accent"]};
    color: #ffffff;
}}
"""


def style_dropdown(combo) -> None:
    """Make a QComboBox's popup list readable and themed."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QListView, QStyledItemDelegate

    view = QListView()
    view.setUniformItemSizes(True)
    combo.setView(view)

    # Row height comes from the DELEGATE. Left to the style sheet, drawing and
    # layout disagree and rows overlap (measured: drawn 34 px, placed 17 px
    # apart). The standard delegate also makes the CSS colours take effect.
    class _RoomyRow(QStyledItemDelegate):
        def sizeHint(self, option, index):  # noqa: N802 - Qt naming
            size = super().sizeHint(option, index)
            size.setHeight(max(size.height() + 12, 30))
            return size

    combo.setItemDelegate(_RoomyRow(combo))
    view.setStyleSheet(_popup_style())
    # Fusion draws item text from the palette, so the palette is set too.
    palette = view.palette()
    palette.setColor(QPalette.Base, QColor(COLOURS["card"]))
    palette.setColor(QPalette.Text, QColor(COLOURS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLOURS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    view.setPalette(palette)
    view.viewport().setAutoFillBackground(True)


def window_size(
    area_width: int,
    area_height: int,
    preferred_width: int,
    preferred_height: int,
    minimum_width: int = 0,
    minimum_height: int = 0,
    margin: int = 40,
) -> tuple[int, int]:
    """A window size that fits the screen.

    Opening at a fixed size pushes the bottom of the window under the taskbar
    on common laptop screens (1366x768), making the buttons there unreachable.
    The preferred size is limited to the screen's AVAILABLE area. Pure
    function, so different resolutions can be tested.
    """
    width = min(preferred_width, max(area_width - margin, 1))
    height = min(preferred_height, max(area_height - margin, 1))
    return max(width, minimum_width), max(height, minimum_height)


def badge(kind: str = "neutral") -> str:
    """Inline style for small status badges (done / missing / info)."""
    c = COLOURS
    pairs = {
        "success": (c["success"], c["success_soft"]),
        "warning": (c["warning"], c["warning_soft"]),
        "error": (c["error"], c["error_soft"]),
        "accent": (c["accent"], c["accent_soft"]),
        "neutral": (c["text_muted"], c["card_alt"]),
    }
    text, background = pairs.get(kind, pairs["neutral"])
    return (
        f"color: {text}; background: {background}; border: 1px solid {c['border']};"
        f" border-radius: 4px; padding: 2px 8px; font-size: 8pt; font-weight: 700;"
    )


def banner(kind: str) -> str:
    """Style for a full-width message strip."""
    c = COLOURS
    pairs = {
        "accent": (c["accent"], c["accent_soft"]),
        "warning": (c["warning"], c["warning_soft"]),
        "success": (c["success"], c["success_soft"]),
        "error": (c["error"], c["error_soft"]),
        "neutral": (c["text_muted"], c["card_alt"]),
    }
    text, background = pairs.get(kind, pairs["accent"])
    return (
        f"color: {text}; background: {background}; border: 1px solid {c['border']};"
        f" border-radius: 6px; padding: 10px;"
    )
