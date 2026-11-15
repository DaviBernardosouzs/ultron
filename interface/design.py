"""Design system nativo: superfícies neutras, energia carmesim e movimento contido."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QListWidget

BACKGROUND = '#050507'
SURFACE = '#111216'
METAL = '#24262C'
ACCENT = '#C8102E'
ENERGY = '#FF243F'
TEXT = '#E6E8EC'
MUTED = '#858B96'
FONT = 'Fira Sans'
MONO = 'FiraCode Nerd Font'
SPACE = (4, 8, 12, 16, 24, 32)
MOTION_MS = 180

STYLE = f"""
QWidget {{ color:{TEXT}; font-family:'{FONT}'; font-size:13px; }}
QWidget#forge, QMainWindow, QDialog {{ background:{BACKGROUND}; }}
QLabel {{ background:transparent; }}
QToolTip {{ background:{SURFACE}; color:{TEXT}; border:1px solid {METAL}; padding:8px; }}
QPushButton {{ background:{SURFACE}; border:1px solid {METAL}; border-radius:4px;
 padding:9px 12px; color:{TEXT}; font-size:11px; font-family:'{MONO}'; }}
QPushButton:hover {{ background:#1B1D23; border-color:#626873; }}
QPushButton:focus {{ border-color:{ENERGY}; }}
QPushButton:pressed, QPushButton:checked {{ background:#30121B; border-color:{ACCENT}; }}
QPushButton:disabled {{ color:#616570; border-color:#202127; }}
QPushButton#enviar {{ background:{ACCENT}; border-color:{ACCENT}; min-width:36px; font-size:18px; }}
QPushButton#enviar:hover {{ background:#E01A37; }}
QPushButton#mic {{ border-radius:24px; color:{ENERGY}; font-size:22px; padding:0; }}
QPushButton#icone {{ font-size:15px; padding:8px; }}
QPushButton#modo {{ text-align:left; }}
QPushButton#perigo {{ color:#FF7787; }}
QPushButton#aprovar, QPushButton#ok {{ color:#A4CBB5; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
 background:#0B0C10; color:{TEXT}; border:1px solid {METAL}; border-radius:4px;
 padding:9px; selection-background-color:#51202D; }}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color:#8A3445; }}
QCheckBox {{ spacing:8px; color:#B5BAC4; font-size:11px; background:transparent; }}
QCheckBox::indicator {{ width:14px; height:14px; border:1px solid #565C68; border-radius:3px; background:#111216; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ENERGY}; }}
QScrollArea {{ background:transparent; border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:7px; margin:0; }}
QScrollBar:horizontal {{ background:transparent; height:7px; margin:0; }}
QScrollBar::handle {{ background:#383C46; border-radius:3px; min-height:28px; min-width:28px; }}
QScrollBar::handle:hover {{ background:#626873; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
QTabWidget::pane {{ border:none; background:{BACKGROUND}; }}
QTabBar::tab {{ background:transparent; color:{MUTED}; padding:10px 12px;
 border-bottom:2px solid transparent; font-size:11px; }}
QTabBar::tab:selected {{ color:{TEXT}; border-bottom:2px solid {ENERGY}; }}
QTabBar::tab:hover {{ color:{TEXT}; background:{SURFACE}; }}
QListWidget, QTableWidget, QTreeWidget {{ background:#0B0C10; alternate-background-color:#101116;
 color:{TEXT}; border:1px solid #202228; border-radius:4px; gridline-color:#202228; }}
QListWidget::item {{ padding:8px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background:#301820; color:{TEXT}; }}
QHeaderView::section {{ background:{SURFACE}; color:#AEB4BF; border:none;
 border-bottom:1px solid {METAL}; padding:10px 8px; font-size:11px; font-family:'{MONO}'; }}
QTableCornerButton::section {{ background:{SURFACE}; border:none; }}
QListWidget#navigation {{ background:transparent; border:none; font-family:'{MONO}'; font-size:11px; }}
QListWidget#navigation::item {{ padding:9px 10px; border-left:2px solid transparent; margin:2px 0; }}
QListWidget#navigation::item:selected {{ border-left:2px solid {ENERGY}; background:#221119; color:{TEXT}; }}
QListWidget#navigation::item:hover {{ background:{SURFACE}; }}
QSplitter::handle {{ background:{METAL}; }}
QDockWidget {{ titlebar-close-icon:none; color:{MUTED}; }}
QDockWidget::title {{ background:{SURFACE}; padding:8px; }}
QLabel#log_eu, QLabel#log_ultron {{ padding:10px 14px; font-size:15px; color:{TEXT}; }}
QLabel#log_ultron {{ border-left:2px solid {ACCENT}; }}
QLabel#log_eu {{ border-left:2px solid #555C69; }}
QLabel#acao {{ color:{MUTED}; font-size:11px; padding:6px 14px; }}
QLabel#dado {{ color:#B5BAC4; }}
QLabel#ponto_on {{ color:#9AC4AA; }}
QLabel#ponto_off {{ color:#626873; }}
QLabel#titulo {{ color:{TEXT}; font-size:24px; font-weight:600; letter-spacing:3px; }}
"""


def navigation(layout, tabs):
    """Preserva a API e as conexões das abas; expõe todos os destinos."""
    rail = QListWidget()
    rail.setObjectName('navigation')
    rail.setAccessibleName('Navegação dos módulos')
    rail.setFixedWidth(190)
    rail.addItems([tabs.tabText(i) for i in range(tabs.count())])
    tabs.tabBar().hide()
    rail.currentRowChanged.connect(tabs.setCurrentIndex)
    tabs.currentChanged.connect(rail.setCurrentRow)
    rail.setCurrentRow(tabs.currentIndex())
    row = QHBoxLayout()
    row.setSpacing(16)
    row.addWidget(rail)
    row.addWidget(tabs, 1)
    layout.addLayout(row, 1)
    tabs._navigation = rail
    from core.config import ajuste
    if not ajuste('visual.movimento_reduzido', False):
        effect = QGraphicsOpacityEffect(tabs)
        effect.setOpacity(1.0)
        tabs.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b'opacity', tabs)
        anim.setDuration(MOTION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        def transition(_):
            anim.stop()
            anim.setStartValue(.65)
            anim.setEndValue(1.)
            anim.start()
        tabs.currentChanged.connect(transition)
        tabs._transition = anim
    return rail
