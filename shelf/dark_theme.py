from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QPalette, QColor

STYLE = '''
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #e4e4e4; }
QMainWindow, QDialog { background: #191919; }
QLabel { background: transparent; }
QLabel#muted { color: #a0a0a0; }
QLabel#title { font-size: 24px; font-weight: 600; color: #eeeeee; }
QLabel#section { font-size: 16px; font-weight: 600; }
QFrame#sidebar { background: #242424; border: none; border-right: 1px solid #303030; }
QFrame#sidebar QLabel { color: #999999; }
QFrame#sidebar QLabel#brand { font-size: 22px; font-weight: 600; color: #ededed; }
QPushButton { background: #292929; border: 1px solid #3c3c3c; border-radius: 7px; padding: 7px 11px; font-weight: 500; }
QPushButton:hover { background: #353535; border-color: #505050; }
QPushButton:pressed { background: #404040; }
QPushButton:disabled { color: #777777; background: #242424; border-color: #303030; }
QPushButton#primary { background: #e3e3e3; color: #202020; border-color: #e3e3e3; }
QPushButton#primary:hover { background: #ffffff; }
QPushButton#primary:disabled { background: #454545; border-color: #454545; color: #888888; }
QPushButton#nav { color: #bdbdbd; background: transparent; border: none; text-align: left; padding: 12px 13px; font-size: 14px; }
QPushButton#nav:hover { background: #2e2e2e; color: white; }
QPushButton#nav:checked { background: #373737; color: #ffffff; }
QFrame#panel, QFrame#card, QFrame#banner { background: #232323; border: 1px solid #333333; border-radius: 12px; }
QFrame#source-card { background: #292929; border: 1px solid #3b3b3b; border-radius: 9px; }
QFrame#source-card:hover { background: #303030; border-color: #555555; }
QLabel#source-badge { color: #cfcfcf; background: #202020; border: 1px solid #444444; border-radius: 6px; padding: 5px 9px; min-width: 100px; }
QFrame#task { background: #282828; border: 1px solid #444444; border-radius: 8px; }
QLineEdit, QComboBox, QPlainTextEdit, QListWidget { background: #222222; border: 1px solid #3a3a3a; border-radius: 7px; padding: 6px; selection-background-color: #454545; selection-color: white; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #808080; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #292929; color: #eeeeee; selection-background-color: #454545; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #737373; border-radius: 4px; background: #262626; }
QCheckBox::indicator:checked { background: #dedede; border: 3px solid #777777; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #555555; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QTabWidget::pane { border: 1px solid #383838; border-radius: 8px; background: #222222; }
QTabBar::tab { padding: 11px 17px; background: #252525; color: #b7b7b7; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #393939; color: #ffffff; }
QProgressBar { border: none; background: #363636; border-radius: 3px; height: 5px; }
QProgressBar::chunk { background: #a5a5a5; border-radius: 3px; }
QToolTip { background: #333333; color: #eeeeee; border: 1px solid #555555; padding: 7px; }
QMessageBox { background: #222222; }
'''


class DarkWindows(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and hasattr(obj, 'isWindow') and obj.isWindow():
            try:
                import ctypes
                enabled = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(obj.winId())), 20, ctypes.byref(enabled), 4)
            except (AttributeError, OSError):
                pass
        return False


def apply_theme(app):
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in [(QPalette.Window, '#191919'), (QPalette.WindowText, '#e4e4e4'),
                        (QPalette.Base, '#222222'), (QPalette.AlternateBase, '#292929'),
                        (QPalette.Text, '#e4e4e4'), (QPalette.Button, '#292929'),
                        (QPalette.ButtonText, '#e4e4e4'), (QPalette.Highlight, '#454545'),
                        (QPalette.HighlightedText, '#ffffff'), (QPalette.PlaceholderText, '#909090')]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    app.dark_windows = DarkWindows(app)
    app.installEventFilter(app.dark_windows)
