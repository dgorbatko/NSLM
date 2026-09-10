import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import threading
import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QListWidgetItem
from shelf.app import MainWindow
from shelf.storage import Store
from shelf.models import Game
from shelf.dialogs import GameDialog, SourceDialog, SettingsDialog, AddGameDialog
from shelf.theme import STYLE
from shelf.widgets import Cover


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    return app


def test_navigation_selection_and_dialogs(app, tmp_path):
    store = Store(tmp_path / 'data')
    window = MainWindow(store, startup=False)
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    window.games = [Game('A game with a very long name that must fit inside a card', str(exe), confidence=90), Game('Second Game', str(exe), '-other', confidence=45, selected=False)]
    window.show()
    app.processEvents()
    window.render_games()
    assert window.art_button.text() == 'Find Artwork'
    assert window.apply_button.text() == 'Add / Update'
    assert window.filter.itemText(5) == 'Artwork incomplete'
    assert window.selection_label.text() == 'Selected: 1'
    window.select_visible()
    assert window.selection_label.text() == 'Selected: 2'
    window.search.setText('Second')
    assert len(window.visible_games()) == 1
    for page in (1, 2, 0):
        window.navigate(page)
        app.processEvents()
    for dialog in [GameDialog(window, window.games[0], store), SourceDialog(window), SettingsDialog(window, store), AddGameDialog(window, store)]:
        dialog.show()
        app.processEvents()
        dialog.close()
    window.close()


def test_editor_updates_local_game_only(app, tmp_path):
    store = Store(tmp_path / 'data')
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    original = Game('Old name', str(exe))
    dialog = GameDialog(None, original, store)
    dialog.name.setText('New name')
    dialog.save()
    assert dialog.result() == QDialog.Accepted
    assert original.name == 'Old name'
    assert dialog.game.name == 'New name'
    assert dialog.game.pending


def test_card_rows_do_not_overlap(app, tmp_path):
    window = MainWindow(Store(tmp_path / 'data'), startup=False)
    window.games = [Game(f'Game {i}', str(tmp_path / 'game.exe'), args=str(i)) for i in range(9)]
    window.show()
    window.render_games()
    app.processEvents()
    first = window.grid.itemAtPosition(0, 0).widget()
    second = window.grid.itemAtPosition(1, 0).widget()
    assert second.y() >= first.y() + first.height()
    cover = first.findChild(Cover)
    assert (first.width(), first.height()) == (180, 341)
    assert cover.height() == 243
    window.close()


def test_artwork_incomplete_filter_and_card_caption(app, tmp_path):
    window = MainWindow(Store(tmp_path / 'data'), startup=False)
    complete = Game('Complete', str(tmp_path / 'complete.exe'), art={kind: f'{kind}.png' for kind in ('portrait', 'landscape', 'hero', 'logo', 'icon')})
    incomplete = Game('Incomplete', str(tmp_path / 'incomplete.exe'), art={'portrait': 'cover.png'})
    window.games = [complete, incomplete]
    window.show()
    window.filter.setCurrentIndex(5)
    window.render_games()
    app.processEvents()
    assert window.visible_games() == [incomplete]
    labels = [item.text() for item in window.grid.itemAtPosition(0, 0).widget().findChildren(
        __import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel)]
    assert '1/5 artworks' in labels
    window.close()


def test_add_game_dialog_creates_valid_game(app, tmp_path):
    store = Store(tmp_path / 'data')
    exe = tmp_path / 'MyStandaloneGame.exe'
    exe.write_bytes(b'fake')
    dialog = AddGameDialog(None, store)
    dialog.exe.setText(str(exe))
    dialog.name.setText('My Standalone Game')
    dialog.args.setText('-windowed')
    dialog.save()
    assert dialog.result() == QDialog.Accepted
    assert dialog.game.name == 'My Standalone Game'
    assert dialog.game.exe == str(exe)
    assert dialog.game.args == '-windowed'
    assert dialog.game.selected
    assert dialog.game.pending


def test_folder_changes_wait_for_save(app, tmp_path):
    store = Store(tmp_path / 'data')
    window = MainWindow(store, startup=False)
    folder = tmp_path / 'Games'
    folder.mkdir()
    window.source_drafts.append({'path': str(folder), 'kind': 'pc', 'emulator': '', 'args_template': '', 'extensions': '.exe', 'enabled': True})
    window.sources_dirty = True
    window.refresh_sources()
    assert store.settings.get('sources', []) == []
    assert window.source_list.itemWidget(window.source_list.item(0)) is not None
    assert 'Windows PC' in window.source_list.itemWidget(window.source_list.item(0)).findChildren(
        __import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel)[-1].text()
    assert window.save_sources_button.isEnabled()
    window.save_sources()
    assert store.settings['sources'][0]['path'] == str(folder)
    assert not window.save_sources_button.isEnabled()
    window.close()


def test_scan_banner_is_the_only_visible_scan_progress(app, tmp_path):
    window = MainWindow(Store(tmp_path / 'data'), startup=False)
    window.show()
    window.scanning_banner.show_scanning('Scanning folders for games...', 'Checking...')
    gate = threading.Event()
    window.run(lambda cancel, progress: gate.wait(2), lambda _: None)
    app.processEvents()
    assert window.scanning_banner.isVisible()
    assert not window.status.isVisible()
    assert not window.progress.isVisible()
    assert not window.cancel_button.isVisible()
    gate.set()
    deadline = time.monotonic() + 3
    while window.worker and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert window.status.isVisible()
    assert not window.scanning_banner.isVisible()
    window.close()


def test_scan_completion_auto_downloads_art_for_new_games_only(app, tmp_path, monkeypatch):
    window = MainWindow(Store(tmp_path / 'data'), startup=False)
    new_game = Game('New game', str(tmp_path / 'new.exe'), art={'icon': 'old-icon.png'})
    old_game = Game('Old game', str(tmp_path / 'old.exe'), existing=True)
    window.games = [new_game, old_game]
    window._auto_artwork_keys = [new_game.key]
    calls = []
    monkeypatch.setattr(window, 'enrich_games', lambda games, automatic=False: calls.append((games, automatic)))
    window.worker = type('FinishedWorker', (), {'deleteLater': lambda self: None})()
    window.finish_work()
    app.processEvents()
    assert calls == [([new_game], True)]
    window.close()


def test_settings_has_no_metadata_credentials(app, tmp_path):
    store = Store(tmp_path / 'data')
    dialog = SettingsDialog(None, store)
    tabs = dialog.findChild(__import__('PySide6.QtWidgets', fromlist=['QTabWidget']).QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ['Steam', 'Artwork']
    dialog.close()


def test_match_selection_opens_gallery_without_replacing_existing_art(app, tmp_path, monkeypatch):
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    dialog = GameDialog(None, Game('Game', str(exe), art={'portrait': 'keep-this.png'}), Store(tmp_path / 'data'))
    item = QListWidgetItem('Exact game')
    item.setData(0x0100, {'id': 42, 'name': 'Exact Game'})
    dialog.matches.addItem(item)
    dialog.matches.setCurrentItem(item)
    calls = []
    monkeypatch.setattr(dialog, 'load_current_gallery', lambda: calls.append(True))
    dialog.choose_match()
    assert dialog.game.sgdb_id == 42
    assert dialog.game.name == 'Exact Game'
    assert dialog.game.art == {'portrait': 'keep-this.png'}
    assert calls == [True]
    dialog.close()


def test_existing_game_mapping_does_not_download_or_replace_art(app, tmp_path):
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    dialog = GameDialog(None, Game('Game', str(exe), existing=True, art={'portrait': 'current.png'}), Store(tmp_path / 'data'))
    dialog.busy = lambda work, done: done(work(threading.Event(), lambda _: None))
    dialog.provider.sgdb_match = lambda game, cancel: setattr(game, 'sgdb_id', 42) or 42
    dialog.resolve_existing_match()
    assert dialog.game.sgdb_id == 42
    assert dialog.game.art == {'portrait': 'current.png'}
    dialog.close()


def test_selected_gallery_art_is_marked(app, tmp_path):
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    dialog = GameDialog(None, Game('Game', str(exe), art_sources={'portrait': 'https://example.test/selected.png'}), Store(tmp_path / 'data'))
    selected = QListWidgetItem('author')
    selected.setData(0x0100, {'id': 1, 'url': 'https://example.test/selected.png', 'author': {'name': 'author'}})
    other = QListWidgetItem('other')
    other.setData(0x0100, {'id': 2, 'url': 'https://example.test/other.png', 'author': {'name': 'other'}})
    dialog.galleries['portrait'].addItem(selected)
    dialog.galleries['portrait'].addItem(other)
    dialog.mark_selected_art('portrait')
    assert selected.text().startswith('✓ ')
    assert not other.text().startswith('✓ ')
    dialog.close()


def test_gallery_loads_official_choices_without_a_steamgriddb_match(app, tmp_path):
    exe = tmp_path / 'Game.exe'
    exe.write_bytes(b'fake')
    dialog = GameDialog(None, Game('Pratfall', str(exe)), Store(tmp_path / 'data'))
    official = {'id': 'steam:cover', 'url': 'https://steamstatic.com/cover.jpg', 'author': {'name': 'Official Steam'}}
    dialog.busy = lambda work, done: done(work(threading.Event(), lambda _: None))
    dialog.provider.gallery_variants = lambda *args, **kwargs: [official]
    dialog.provider.download = lambda *args, **kwargs: str(exe)
    dialog.load_gallery('portrait')
    assert dialog.galleries['portrait'].count() == 1
    assert dialog.galleries['portrait'].item(0).text() == 'Official Steam'
    dialog.close()
