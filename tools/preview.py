"""Render the actual Qt widgets into images using isolated, synthetic data."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from shelf.app import MainWindow
from shelf.storage import Store
from shelf.models import Game
from shelf.dialogs import GameDialog
from shelf.theme import apply_theme

output = Path(__file__).resolve().parents[1] / 'artifacts'
output.mkdir(exist_ok=True)
app = QApplication([])
for name in ['segoeui.ttf', 'segoeuib.ttf', 'segoeuil.ttf', 'seguisb.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
apply_theme(app)
with tempfile.TemporaryDirectory() as temp:
    store = Store(Path(temp) / 'data')
    window = MainWindow(store, startup=False)
    window.show()
    window.render_games()
    app.processEvents()
    window.grab().save(str(output / 'first-launch.png'))
    exe = Path(temp) / 'Game.exe'
    exe.write_bytes(b'fixture')
    window.games = [Game(name, str(exe), args=str(index), confidence=confidence, existing=existing, selected=not existing and confidence > 60, kind=kind)
        for index, (name, confidence, existing, kind) in enumerate([
            ('Hollow Knight', 94, False, 'pc'), ('The Legend of Zelda', 85, False, 'eden'), ('Stardew Valley', 100, True, 'pc'),
            ('Outer Wilds', 48, False, 'pc'), ('Celeste', 95, False, 'pc'), ('TUNIC', 100, True, 'pc')])]
    window.render_games()
    window.status.setText('Interface preview · sample data')
    app.processEvents()
    window.grab().save(str(output / 'library-preview.png'))
    dialog = GameDialog(window, window.games[0], store)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(output / 'editor-preview.png'))
    dialog.tabs.setCurrentIndex(2)
    app.processEvents()
    dialog.grab().save(str(output / 'artwork-preview.png'))
    dialog.close()
    window.close()
