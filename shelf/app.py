import copy
from dataclasses import asdict
from pathlib import Path
import os
import re
import sys
from PySide6.QtCore import Qt, QTimer, QUrl, QLockFile, QSize
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QColor, QPen
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QScrollArea, QLineEdit, QComboBox, QCheckBox, QProgressBar, QMessageBox, QFileDialog,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QLayout)
from .models import Game, ART_TYPES, is_emulator, normal_path, normalized_title
from .storage import Store, data_dir
from .widgets import label, button, panel, Worker, GameCard, Cover, ScanningBanner, FilterComboBox
from .dialogs import SourceDialog, SettingsDialog, GameDialog, AddGameDialog
from .providers import Providers
from .scanner import scan
from . import steam
from .theme import STYLE, apply_theme


class ActivitySpinner(QWidget):
    """Small indeterminate activity indicator for operations that must wait."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.setFixedSize(38, 38)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(55)

    def advance(self):
        self.angle = (self.angle + 22) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#f2f2f2'), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(6, 6, 26, 26, -self.angle * 16, 245 * 16)
        painter.end()


class SteamUpdateProgress(QDialog):
    """A non-dismissible status window while Steam files are being changed."""
    def closeEvent(self, event):
        event.ignore()


def matching_existing(game, remaining):
    """Return one confidently matching Steam shortcut without guessing between games."""
    exact = remaining.get(game.key)
    if exact:
        return exact
    if is_emulator(game.kind):
        def rom_target(item):
            source = str(getattr(item, 'source', '') or '')
            if Path(source).suffix.casefold() in {'.nsp', '.xci', '.nro', '.iso', '.chd', '.rvz', '.zip'}:
                return source.replace('/', '\\').strip(' "').casefold()
            command = f'{item.exe} {item.args}'
            matches = re.findall(r'(?i)([a-z]:[\\/][^"\r\n]+?\.(?:nsp|xci|nro|iso|chd|rvz|zip))', command)
            return matches[-1].replace('/', '\\').strip(' "').casefold() if matches else ''

        target = rom_target(game)
        matches = [item for item in remaining.values() if target and rom_target(item) == target]
        if len(matches) == 1:
            return matches[0]
        title_id = re.search(r'(?i)\b010[0-9a-f]{13}\b', target)
        if title_id:
            matches = [item for item in remaining.values()
                       if title_id.group(0).casefold() in f'{item.exe} {item.args} {item.name}'.casefold()]
            if len(matches) == 1:
                return matches[0]
        return None
    if game.kind not in {'pc', 'linux_pc'}:
        return None
    executable_paths = {normal_path(game.exe), *(normal_path(path) for path in game.alternatives)}
    matches = [item for item in remaining.values() if normal_path(item.exe) in executable_paths]
    if len(matches) == 1:
        return matches[0]
    try:
        folder = Path(game.source).resolve()
        inside = [item for item in remaining.values()
                  if Path(item.exe.strip('"')).resolve().is_relative_to(folder)]
    except (OSError, ValueError):
        inside = []
    if len(inside) == 1:
        return inside[0]
    title_matches = [item for item in inside
                     if normalized_title(item.name) == normalized_title(game.name)]
    return title_matches[0] if len(title_matches) == 1 else None


def needs_launcher_repair(scanned, existing):
    """Flag an existing PC shortcut only when a verified replacement exists locally."""
    if scanned.kind not in {'pc', 'linux_pc'}:
        return False
    try:
        return Path(scanned.exe).is_file() and not Path(existing.exe.strip('"')).is_file()
    except OSError:
        return False


class MainWindow(QMainWindow):
    def __init__(self, store=None, startup=True):
        super().__init__()
        self.store = store or Store()
        self.games, self.worker, self.page = [], None, 0
        self._auto_artwork_keys = []
        self.source_drafts = copy.deepcopy(self.store.settings.get('sources', []))
        self.sources_dirty = False
        self.setWindowTitle('NSLM — Non Steam Library Manager')
        self.resize(1240, 840)
        self.setMinimumSize(1040, 730)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 24, 14, 18)
        brand = label('NSLM', 'brand')
        side.addWidget(brand)
        subtitle = label('NON-STEAM\nLIBRARY MANAGER', wrap=True)
        subtitle.setStyleSheet('font-size: 10px; letter-spacing: .3px;')
        side.addWidget(subtitle)
        side.addSpacing(28)
        self.nav = []
        for index, text in enumerate(['Library', 'Folders', 'Backups']):
            item = button(text, lambda _=False, i=index: self.navigate(i))
            item.setObjectName('nav')
            item.setCheckable(True)
            self.nav.append(item)
            side.addWidget(item)
        side.addStretch()
        note = label(' ', wrap=True)
        note.setStyleSheet('color: #91aa99; line-height: 1.5;')
        side.addWidget(note)
        side.addSpacing(22)
        settings = button('Settings', self.settings)
        settings.setObjectName('nav')
        side.addWidget(settings)
        side.addWidget(label('NSLM  /  0.1'))
        outer.addWidget(sidebar)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(22, 20, 22, 12)
        body.setSpacing(10)
        outer.addWidget(self.body, 1)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.build_library()
        self.build_sources()
        self.build_backups()
        footer = QHBoxLayout()
        self.status = label('Ready', 'muted', True)
        footer.addWidget(self.status, 1)
        self.cancel_button = button('Cancel', self.cancel_work)
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        body.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        body.addWidget(self.progress)
        self.navigate(0)
        if not self.store.settings.get('steam'):
            self.store.settings['steam'] = steam.discover_steam()
        candidates = steam.profiles(self.store.settings.get('steam', ''))
        if not self.store.settings.get('profile') and len(candidates) == 1:
            self.store.settings['profile'] = candidates[0][0]
        if startup:
            QTimer.singleShot(100, self.startup)

    def heading(self, layout, title, subtitle):
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle, 'muted', True))

    def build_library(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        top = QHBoxLayout()
        headings = QVBoxLayout()
        self.heading(headings, 'Library', 'Manage non-Steam games and artwork.')
        top.addLayout(headings, 1)
        self.rescan = button('Rescan', self.scan_games)
        top.addWidget(self.rescan)
        layout.addLayout(top)
        banner, line = panel(QHBoxLayout, 'banner')
        line.addWidget(label('Add a game manually or manage scan folders.', 'muted'), 1)
        line.addWidget(button('Add game', self.add_game, True))
        line.addWidget(button('Manage folders', lambda: self.navigate(1)))
        layout.addWidget(banner)
        self.scanning_banner = ScanningBanner(self.cancel_work)
        self.scanning_banner.hide()
        layout.addWidget(self.scanning_banner)
        self.stats = label('0 games   ·   0 new   ·   0 to review', 'muted')
        layout.addWidget(self.stats)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search games...')
        self.search.textChanged.connect(self.render_games)
        row.addWidget(self.search, 1)
        self.filter = FilterComboBox()
        self.filter.addItems(['All games', 'New', 'In Steam', 'Review needed', 'Emulators / Switch', 'Artwork incomplete'])
        self.filter.setToolTip('Choose which games to show')
        self.filter.currentIndexChanged.connect(self.render_games)
        row.addWidget(self.filter)
        row.addWidget(button('Select visible', self.select_visible))
        row.addWidget(button('Clear selection', self.clear_selection))
        layout.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_body = QWidget()
        self.grid = QGridLayout(self.grid_body)
        self.grid.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.grid.setContentsMargins(0, 2, 4, 2)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_body)
        layout.addWidget(self.scroll, 1)
        footer, row = panel(QHBoxLayout)
        self.selection_label = label('Selected: 0')
        row.addWidget(self.selection_label, 1)
        self.art_button = button('Find Artwork', self.enrich_selected)
        row.addWidget(self.art_button)
        self.apply_button = button('Add / Update', self.apply_selected, True)
        row.addWidget(self.apply_button)
        layout.addWidget(footer)
        self.stack.addWidget(page)

    def build_sources(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading(layout, 'Folders', 'Manage folders included in scans.')
        layout.addSpacing(15)
        self.source_list = QListWidget()
        self.source_list.setSpacing(8)
        self.source_list.itemDoubleClicked.connect(self.edit_source)
        layout.addWidget(self.source_list, 1)
        row = QHBoxLayout()
        row.addWidget(button('Add folder', self.add_source, True))
        row.addWidget(button('Edit', self.edit_source))
        row.addWidget(button('Remove', self.remove_source))
        row.addStretch()
        self.save_sources_button = button('Save folders', self.save_sources, True)
        self.save_sources_button.setEnabled(False)
        row.addWidget(self.save_sources_button)
        layout.addLayout(row)
        card, content = panel(name='banner')
        content.addWidget(label('Folder types', 'section'))
        pc_label = 'Windows / Proton' if sys.platform != 'win32' else 'Windows'
        content.addWidget(label(f'{pc_label}: a folder containing games. Linux: a folder containing native Linux games. Switch: a ROM folder and emulator launcher. Scanning never changes Steam.', 'muted', True))
        layout.addWidget(card)
        self.stack.addWidget(page)

    def build_backups(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.heading(layout, 'Backups', 'Back up non-Steam shortcuts and artwork for the selected profile.')
        layout.addSpacing(15)
        card, content = panel(name='banner')
        content.addWidget(label('Automatic backups', 'section'))
        content.addWidget(label('A backup is created before each Steam update or restore. Backups include shortcuts and artwork, not game files or saves.', 'muted', True))
        layout.addWidget(card)
        self.backup_list = QListWidget()
        self.backup_list.setSpacing(7)
        layout.addWidget(self.backup_list, 1)
        row = QHBoxLayout()
        row.addWidget(button('Create backup', self.make_backup, True))
        row.addWidget(button('Restore selected', self.restore_selected))
        row.addWidget(button('From file...', self.restore_file))
        row.addWidget(button('Open folder', self.open_backups))
        layout.addLayout(row)
        self.stack.addWidget(page)

    def navigate(self, index):
        self.page = index
        self.stack.setCurrentIndex(index)
        for i, item in enumerate(self.nav):
            item.setChecked(i == index)
        if index == 0:
            self.render_games()
        elif index == 1:
            self.refresh_sources()
        else:
            self.refresh_backups()

    @property
    def backup_dir(self):
        path = self.store.root / 'backups'
        path.mkdir(exist_ok=True)
        return path

    def config(self):
        return steam.config_path(self.store.settings.get('steam', ''), self.store.settings.get('profile', ''))

    def startup(self):
        self.load_library()

    def catalog_key(self, game_key):
        return self.store.settings.get('profile', '') + ':' + game_key

    def load_library(self):
        try:
            self.games = steam.library(self.config())
            for game in self.games:
                saved = self.store.catalog.get(self.catalog_key(game.key), {})
                # Steam owns the local artwork paths; NSLM retains only the
                # source URL so the editor can mark the current gallery image.
                for field in ('sgdb_id', 'art_sources'):
                    if field in saved:
                        setattr(game, field, saved[field])
                if saved.get('pending'):
                    for field in ('name', 'exe', 'args', 'art', 'start_dir', 'pending'):
                        if field in saved:
                            setattr(game, field, saved[field])
                    game.selected = True
            self.status.setText(f'Profile {self.store.settings["profile"]} · non-Steam games: {len(self.games)}')
        except Exception as error:
            self.status.setText(str(error))
        self.render_games()

    def visible_games(self):
        text, index = self.search.text().casefold(), self.filter.currentIndex()
        def matches_filter(game):
            return (
                index == 0 or
                index == 1 and not game.existing or
                index == 2 and game.existing or
                index == 3 and game.confidence < 60 or
                index == 4 and is_emulator(game.kind) or
                index == 5 and len(game.art) < len(ART_TYPES)
            )
        return [game for game in self.games if text in game.name.casefold() and matches_filter(game)]

    def render_games(self, *_):
        if not hasattr(self, 'grid'):
            return
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        visible = self.visible_games()
        if not visible:
            frame, contents = panel()
            contents.setContentsMargins(34, 42, 34, 42)
            contents.addWidget(label('No games to display', 'section'))
            contents.addWidget(label('Add a game folder or select your Steam profile in Settings.' if not self.games else 'No matches. Try a different search or filter.', 'muted', True))
            contents.addSpacing(16)
            contents.addWidget(button('Manage folders', lambda: self.navigate(1), True), alignment=Qt.AlignLeft)
            self.grid.addWidget(frame, 0, 0, 1, 3)
        else:
            columns = max(3, min(8, (self.width() - 230) // 190))
            for index, game in enumerate(visible):
                self.grid.addWidget(GameCard(game, self.edit_game, self.update_selection), index // columns, index % columns)
            for column in range(8):
                self.grid.setColumnStretch(column, 0)
        self.stats.setText(f'{len(self.games)} games   ·   {sum(not g.existing for g in self.games)} new   ·   {sum(g.confidence < 60 for g in self.games)} to review')
        columns = max(3, min(8, (self.width() - 230) // 190))
        rows = (len(visible) + columns - 1) // columns
        self.grid_body.setMinimumHeight(rows * 352 if visible else 180)
        self.update_selection()

    def update_selection(self):
        selected = [g for g in self.games if g.selected]
        self.selection_label.setText(f'Selected: {len(selected)}')
        self.apply_button.setEnabled(bool(selected) and not self.worker)
        self.art_button.setEnabled(bool(selected) and not self.worker)

    def select_visible(self):
        for game in self.visible_games():
            game.selected = True
        self.render_games()

    def clear_selection(self):
        for game in self.games:
            game.selected = False
        self.render_games()

    def on_worker_progress(self, message):
        self.status.setText(message)
        if hasattr(self, 'scanning_banner') and self.scanning_banner.isVisible():
            self.scanning_banner.set_status(message)

    def run(self, function, done, cancellable=True, failed=None, progress_hook=None):
        if self.worker:
            return
        self.rescan.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.art_button.setEnabled(False)
        for item in self.nav:
            item.setEnabled(False)
        inline_scan = hasattr(self, 'scanning_banner') and self.scanning_banner.isVisible()
        self.status.setVisible(not inline_scan)
        self.progress.setVisible(not inline_scan)
        self.cancel_button.setVisible(cancellable and not inline_scan)
        self.worker = Worker(function, self)
        self.worker.result.connect(done)
        self.worker.progress.connect(self.on_worker_progress)
        if progress_hook:
            self.worker.progress.connect(progress_hook)
        self.worker.failed.connect(failed or self.error)
        self.worker.finished.connect(self.finish_work)
        self.worker.start()

    def finish_work(self):
        self.worker.deleteLater()
        self.worker = None
        if hasattr(self, 'scanning_banner'):
            self.scanning_banner.hide_scanning()
        self.status.show()
        self.rescan.setEnabled(True)
        for item in self.nav:
            item.setEnabled(True)
        self.progress.hide()
        self.cancel_button.hide()
        self.update_selection()
        if self._auto_artwork_keys:
            keys, self._auto_artwork_keys = set(self._auto_artwork_keys), []
            QTimer.singleShot(0, lambda: self.enrich_games(
                [game for game in self.games if game.key in keys and not game.existing], automatic=True))

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText('Cancelling...')
            if hasattr(self, 'scanning_banner') and self.scanning_banner.isVisible():
                self.scanning_banner.set_status('Cancelling...')

    def error(self, error):
        self.status.setText(str(error))
        if not isinstance(error, InterruptedError):
            QMessageBox.warning(self, 'Operation failed', str(error))

    def scan_games(self):
        if self.worker:
            return
        if not self.store.settings.get('sources'):
            self.add_source()
            return
        sources = copy.deepcopy(self.store.settings['sources'])
        self.navigate(0)
        if hasattr(self, 'scanning_banner'):
            self.scanning_banner.show_scanning('Scanning folders for games...', 'Checking folders and executables...')
        def done(result):
            scanned, warnings = result
            try:
                existing = steam.library(self.config())
                native_games = steam.installed_native_games(self.store.settings.get('steam', ''))
            except Exception as error:
                # Do not treat an unreadable Steam library as empty: that would hide duplicate uncertainty.
                self.error(error)
                return
            by_key = {g.key: g for g in existing}
            found = []
            native_skipped = 0
            for game in scanned:
                saved = self.store.catalog.get(self.catalog_key(game.key))
                if saved:
                    # Auto-detected names must be allowed to improve on the next scan.
                    # Pending records contain explicit edits/artwork that are not in Steam yet.
                    fields = ['sgdb_id', 'art', 'art_sources', 'start_dir', 'pending']
                    if saved.get('pending'):
                        fields += ['name', 'exe', 'args', 'search_names']
                    for field in fields:
                        if field in saved:
                            setattr(game, field, saved[field])
                    game.confidence = saved.get('confidence', game.confidence)
                    if game.pending:
                        game.selected = True
                previous = matching_existing(game, by_key)
                native = steam.native_match(game, native_games)
                if native and not previous:
                    native_skipped += 1
                    continue
                if previous:
                    by_key.pop(previous.key, None)
                if previous:
                    game.appid, game.existing, game.selected = previous.appid, True, game.pending
                    game.start_dir = game.start_dir or previous.start_dir
                    game.art = {**previous.art, **game.art} if game.pending else previous.art
                    if not game.pending:
                        game.name = previous.name
                    if needs_launcher_repair(game, previous):
                        game.pending = True
                        game.selected = True
                        game.confidence = min(game.confidence, 59)
                        game.reasons.append('Existing Steam executable is missing; a replacement was detected')
                found.append(game)
            self.games = found + list(by_key.values())
            # A fresh scan is a fresh decision: select only genuinely new
            # games, never invisible review/pending cards from an older scan.
            for game in self.games:
                game.selected = not game.existing
            # A previous SteamGridDB fallback is not a completed set when
            # official Steam artwork is now available. Revisit those new cards
            # as well as genuinely incomplete cards.
            self._auto_artwork_keys = [
                game.key for game in found
                if not game.existing and (
                    len(game.art) < len(ART_TYPES) or
                    any(Providers.is_community_art(source) for source in game.art_sources.values())
                )
            ]
            self.persist()
            self.filter.setCurrentIndex(1)
            self.render_games()
            self.status.setText(f'Scan complete. New games: {sum(not g.existing for g in found)}.' +
                                (f' Native Steam games skipped: {native_skipped}.' if native_skipped else '') +
                                (f' Folder warnings: {len(warnings)}.' if warnings else ''))
            if warnings:
                QMessageBox.information(self, 'Scan results', '\n'.join(warnings[:30]))
        self.run(lambda cancel, progress: scan(sources, cancel, progress), done)

    def persist(self):
        for game in self.games:
            self.store.catalog[self.catalog_key(game.key)] = game.to_dict()
        self.store.save()

    def edit_game(self, game):
        if self.worker:
            return
        try:
            dialog = GameDialog(self, game, self.store)
            if dialog.exec() == QDialog.Accepted:
                original_key = game.key
                self.games[self.games.index(game)] = dialog.game
                self.store.catalog[self.catalog_key(original_key)] = dialog.game.to_dict()
                self.persist()
                self.render_games()
        except Exception as error:
            self.error(error)

    def enrich_selected(self):
        if self.worker:
            return
        selected = [g for g in self.games if g.selected]
        if not selected:
            self.status.setText('Select one or more games to download artwork.')
            return
        self.enrich_games(selected)

    def enrich_games(self, games, automatic=False):
        if not games:
            return
        try:
            provider = Providers(self.store)
        except Exception as error:
            self.error(error)
            return
        def done(result):
            by_key = {g.key: g for g in result}
            self.games = [by_key.get(g.key, g) for g in self.games]
            self.persist()
            self.render_games()
            problems = [g for g in result if g.note]
            prefix = 'Automatic artwork finished' if automatic else 'Artwork finished'
            self.status.setText(f'{prefix} for {len(result)} games.' + (f' {len(problems)} need review.' if problems else ''))
        if automatic and hasattr(self, 'scanning_banner'):
            self.scanning_banner.show_scanning('Finding official artwork...', 'Checking Steam artwork for newly found games...')
        self.run(lambda cancel, progress: provider.enrich(games, cancel, progress), done)

    def apply_selected(self):
        if self.worker:
            return
        selected = [copy.deepcopy(g) for g in self.games if g.selected]
        if not selected:
            return
        try:
            config = self.config()
            available_collections = steam.collections(config)
        except Exception as error:
            self.error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Update Steam')
        dialog.resize(610, 540)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.addWidget(label('Review changes', 'section'))
        new_count = sum(not game.existing for game in selected)
        existing_count = len(selected) - new_count
        summary = f'{new_count} new game{"s" if new_count != 1 else ""} selected'
        if existing_count:
            summary += f' · {existing_count} existing game{"s" if existing_count != 1 else ""} selected'
        layout.addWidget(label(summary + f'\nSteam profile: {self.store.settings["profile"]}\nSteam will close during the update. A backup will be created first. It will stay closed afterwards unless you choose Launch Steam.', 'muted', True))
        listing = QListWidget()
        for game in selected:
            state = 'in Steam' if game.existing else 'new game'
            listing.addItem(f'{game.name}  ·  {state}  ·  {len(game.art)}/5 images')
        layout.addWidget(listing, 1)
        collection_items = []
        if available_collections:
            layout.addWidget(label('Add to Steam collections (optional)', 'section'))
            layout.addWidget(label('Leave everything unchecked to add games to Uncategorized, as before.', 'muted', True))
            collection_list = QListWidget()
            collection_list.setMaximumHeight(min(112, 30 * len(available_collections) + 8))
            for collection_name, _tag in available_collections:
                item = QListWidgetItem(collection_name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                collection_list.addItem(item)
                collection_items.append(item)
            layout.addWidget(collection_list)
        overwrite = QCheckBox('Update selected games already in Steam')
        layout.addWidget(overwrite)
        layout.addWidget(label('Existing entries are skipped unless this option is enabled.', 'muted', True))
        force = QCheckBox('Force-close Steam if it does not respond')
        layout.addWidget(force)
        layout.addWidget(label('Close running games before continuing.', 'muted'))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Update Steam')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancel')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        overwrite_value, force_value = overwrite.isChecked(), force.isChecked()
        selected_collections = [item.text() for item in collection_items if item.checkState() == Qt.Checked]
        settings = dict(self.store.settings)
        progress_dialog = SteamUpdateProgress(self)
        progress_dialog.setWindowTitle('Adding games to Steam')
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        progress_dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
        progress_dialog.setFixedWidth(470)
        progress_layout = QVBoxLayout(progress_dialog)
        progress_layout.setContentsMargins(28, 25, 28, 25)
        progress_layout.setSpacing(14)
        row = QHBoxLayout()
        row.addWidget(ActivitySpinner())
        title_box = QVBoxLayout()
        title_box.addWidget(label('Adding games to Steam', 'section'))
        progress_detail = label('Preparing the update…', 'muted', True)
        title_box.addWidget(progress_detail)
        row.addLayout(title_box, 1)
        progress_layout.addLayout(row)
        progress_layout.addWidget(label('Please wait. Steam may take a few seconds to close before NSLM can safely update shortcuts and artwork.', 'muted', True))
        progress_dialog.show()
        def done(result):
            progress_dialog.accept()
            changed = dict(result['changed'])
            for game in self.games:
                if game.selected and game.name in changed:
                    game.existing, game.appid, game.selected = True, changed[game.name], False
                    game.pending = False
            # Reload authoritative IDs to handle same-title games correctly.
            current = {g.key: g for g in steam.library(self.config())}
            for game in self.games:
                if game.key in current:
                    game.appid, game.existing = current[game.key].appid, True
            self.persist()
            self.render_games()
            changed_count, skipped_count = len(result['changed']), len(result['skipped'])
            self.status.setText(f'Steam updated. Added / updated: {changed_count}. Skipped: {skipped_count}. Steam remains closed.')
            collection_note = f' Added to: {", ".join(selected_collections)}.' if selected_collections else ''
            complete = QDialog(self)
            complete.setWindowTitle('Steam library updated')
            complete.setFixedWidth(520)
            complete_layout = QVBoxLayout(complete)
            complete_layout.setContentsMargins(28, 25, 28, 25)
            complete_layout.setSpacing(14)
            complete_layout.addWidget(label('Steam library updated', 'section'))
            complete_layout.addWidget(label(
                f'Added / updated: {changed_count}.\nSkipped: {skipped_count}.{collection_note}\n\n'
                'The new cards have been removed from this list. Steam is closed; launch it only when you are ready.',
                'muted', True))
            complete_buttons = QHBoxLayout()
            complete_buttons.addStretch()
            complete_buttons.addWidget(button('OK', complete.accept))
            def launch_steam():
                steam.restart(settings['steam'])
                complete.accept()
            complete_buttons.addWidget(button('Launch Steam', launch_steam, True))
            complete_layout.addLayout(complete_buttons)
            complete.exec()
        def failed(error):
            progress_dialog.reject()
            self.error(error)
        self.run(lambda cancel, progress: steam.apply(settings['steam'], settings['profile'], selected, self.backup_dir,
                    overwrite=overwrite_value, force=force_value, launch=False,
                    collections=selected_collections, progress=progress), done, cancellable=False,
                 failed=failed, progress_hook=progress_detail.setText)

    def settings(self):
        if self.worker:
            return
        try:
            before = (self.store.settings.get('steam'), self.store.settings.get('profile'))
            dialog = SettingsDialog(self, self.store)
            if dialog.exec() == QDialog.Accepted:
                if before != (self.store.settings.get('steam'), self.store.settings.get('profile')):
                    self.load_library()
                self.status.setText('Settings saved.')
        except Exception as error:
            self.error(error)

    def add_game(self):
        if self.worker:
            return
        dialog = AddGameDialog(self, self.store)
        if dialog.exec() == QDialog.Accepted and dialog.game:
            game = dialog.game
            existing = next((g for g in self.games if g.key == game.key), None)
            if existing:
                idx = self.games.index(existing)
                self.games[idx] = game
            else:
                self.games.insert(0, game)
            self.store.catalog[self.catalog_key(game.key)] = game.to_dict()
            self.store.save()
            self.render_games()
            self.status.setText(f'Added "{game.name}" to library. Click Add / update to sync with Steam.')

    def add_source(self):
        if self.worker:
            return
        dialog = SourceDialog(self)
        if dialog.exec() == QDialog.Accepted:
            value = asdict(dialog.value())
            sources = self.source_drafts
            if any(Path(s['path']).resolve() == Path(value['path']).resolve() and s['kind'] == value['kind'] for s in sources):
                self.status.setText('This folder is already listed.')
                return
            sources.append(value)
            self.sources_dirty = True
            self.refresh_sources()
            self.status.setText('Folder added. Add more folders or click Save folders.')

    def refresh_sources(self):
        self.source_list.clear()
        for source in self.source_drafts:
            k = source.get('kind', 'pc')
            if k == 'switch_ryujinx':
                kind = 'Nintendo Switch · Ryujinx'
            elif k in {'switch_yuzu', 'eden'}:
                kind = 'Nintendo Switch · Yuzu'
            elif k == 'custom':
                kind = 'Custom Emulator'
            elif k == 'linux_pc':
                kind = 'Linux PC'
            else:
                kind = 'Windows / Proton' if sys.platform != 'win32' else 'Windows PC'
            state = 'Enabled' if source.get('enabled', True) else 'Disabled'
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 74))
            self.source_list.addItem(item)
            card = QFrame()
            card.setObjectName('source-card')
            content = QHBoxLayout(card)
            content.setContentsMargins(14, 9, 14, 9)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(label(Path(source['path']).name or source['path'], 'section'))
            text.addWidget(label(source['path'], 'muted', True))
            content.addLayout(text, 1)
            badge = label(f'{kind}\n{state}', 'source-badge', True)
            badge.setAlignment(Qt.AlignCenter)
            content.addWidget(badge)
            self.source_list.setItemWidget(item, card)
        self.save_sources_button.setEnabled(self.sources_dirty)

    def edit_source(self, *_):
        index = self.source_list.currentRow()
        if index < 0:
            return
        from .models import Source
        dialog = SourceDialog(self, Source(**self.source_drafts[index]))
        if dialog.exec() == QDialog.Accepted:
            self.source_drafts[index] = asdict(dialog.value())
            self.sources_dirty = True
            self.refresh_sources()

    def remove_source(self):
        index = self.source_list.currentRow()
        if index >= 0:
            self.source_drafts.pop(index)
            self.sources_dirty = True
            self.refresh_sources()
            self.status.setText('Folder removed from the list. Game files were not changed.')

    def save_sources(self):
        self.store.settings['sources'] = copy.deepcopy(self.source_drafts)
        self.store.save()
        self.sources_dirty = False
        self.save_sources_button.setEnabled(False)
        self.status.setText('Folders saved. Open Library and click Rescan when ready.')

    def refresh_backups(self):
        self.backup_list.clear()
        profile = self.store.settings.get('profile', '')
        paths = set(self.backup_dir.glob(f'NSLM-{profile}-*.zip')) | set(self.backup_dir.glob(f'SteamShelf-{profile}-*.zip'))
        for path in sorted(paths, reverse=True):
            item = QListWidgetItem(f'{path.stem}\n{path.stat().st_size / 1024 / 1024:.1f} MB')
            item.setData(Qt.UserRole, str(path))
            self.backup_list.addItem(item)

    def make_backup(self):
        try:
            config = self.config()
        except Exception as error:
            self.error(error)
            return
        def work(cancel, progress):
            progress('Creating backup...')
            before = steam.fingerprint(config)
            path = steam.backup(config, self.backup_dir)
            manifest = steam.read_backup(path, self.store.settings['profile'])
            import hashlib
            if before != steam.fingerprint(config) or before != {k: hashlib.sha256(v).hexdigest() for k, v in manifest.items()}:
                path.unlink()
                raise RuntimeError('Steam changed files during backup. Close Steam and try again.')
            return path
        def done(path):
            self.status.setText('Backup saved: ' + path.name)
            self.refresh_backups()
        self.run(work, done, cancellable=False)

    def open_backups(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_dir)))

    def restore_selected(self):
        item = self.backup_list.currentItem()
        if item:
            self.restore_archive(item.data(Qt.UserRole))

    def restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'NSLM backup', str(self.backup_dir), 'Backup (*.zip)')
        if path:
            self.restore_archive(path)

    def restore_archive(self, path):
        answer = QMessageBox.question(self, 'Restore backup?', f'Backup: {Path(path).name}\n\nThe current shortcuts and artwork for profile {self.store.settings.get("profile")} will be replaced by this backup. The current state will be backed up first. Steam will close temporarily.', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        settings = dict(self.store.settings)
        def done(saved):
            prefix = self.store.settings.get('profile', '') + ':'
            for key, data in self.store.catalog.items():
                if key.startswith(prefix):
                    data['pending'] = False
            self.load_library()
            self.refresh_backups()
            self.status.setText(f'Restored from backup: {Path(path).name}')
        def work(cancel, progress):
            progress('Restoring backup...')
            return steam.restore(settings.get('steam'), settings.get('profile'), path, self.backup_dir, launch=settings.get('restart', True), progress=progress)
        self.run(work, done, cancellable=False)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(self, 'NSLM', 'A task is still running. Do you want to cancel it and exit?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(2000)
        if self.store:
            self.persist()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('NSLM')
    app.setOrganizationName('NSLM')
    apply_theme(app)
    app.setFont(QFont('Segoe UI', 10))
    lock = QLockFile(str(data_dir() / 'application.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None, 'NSLM', 'NSLM is already running.')
        return 0
    def exception_hook(kind, value, traceback):
        import traceback as tb
        with (data_dir() / 'error.log').open('a', encoding='utf-8') as log:
            tb.print_exception(kind, value, traceback, file=log)
        QMessageBox.warning(None, 'NSLM', f'An error occurred: {value}\nDetails were saved to error.log.')
    sys.excepthook = exception_hook
    try:
        window = MainWindow()
    except Exception as error:
        QMessageBox.critical(None, 'NSLM', str(error))
        return 1
    icon = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent)) / 'assets' / 'icon.ico'
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))
    window.show()
    smoke = os.environ.get('NSLM_SMOKE_DIRECTORY', os.environ.get('STEAMSHELF_SMOKE_DIRECTORY'))
    if smoke:
        import time
        smoke_started = time.monotonic()
        def finish_smoke():
            if window.worker and time.monotonic() - smoke_started < 20:
                QTimer.singleShot(100, finish_smoke)
                return
            import json
            output = Path(smoke)
            output.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output / 'packaged-window.png'))
            (output / 'smoke.json').write_text(json.dumps({'window': window.windowTitle(), 'visible': window.isVisible(), 'pages': window.stack.count()}), 'utf-8')
            window.close()
        QTimer.singleShot(150, window.scan_games)
        QTimer.singleShot(300, finish_smoke)
    return app.exec()
