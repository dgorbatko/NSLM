import os
import copy
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize, QTimer
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox,
    QFileDialog, QDialogButtonBox, QMessageBox, QTabWidget, QWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QScrollArea)
from .models import Game, Source, ART_TYPES, clean_name, is_emulator
from .widgets import label, button, panel, Worker, Cover
from .providers import Providers
from . import steam


class SourceDialog(QDialog):
    def __init__(self, parent, source=None):
        super().__init__(parent)
        self.setWindowTitle('Game folder')
        self.setMinimumWidth(640)
        source = source or Source('')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.addWidget(label('Add folder source', 'section'))
        layout.addWidget(label('Select a folder containing PC games, or a ROM directory for an emulator.', 'muted', True))
        form = QFormLayout()
        self.source_form = form
        self.kind = QComboBox()
        self.kind.addItem('Windows / Proton Games' if os.name != 'nt' else 'Windows PC Games', 'pc')
        if os.name != 'nt':
            self.kind.addItem('Native Linux Games', 'linux_pc')
        self.kind.addItem('Nintendo Switch · Ryujinx (EmuDeck)', 'switch_ryujinx')
        self.kind.addItem('Nintendo Switch · Yuzu / Eden / Suyu', 'switch_yuzu')
        self.kind.addItem('Custom Emulator / ROMs', 'custom')

        cur_kind = source.kind
        if cur_kind == 'eden':
            cur_kind = 'switch_yuzu'
        idx = self.kind.findData(cur_kind)
        self.kind.setCurrentIndex(max(0, idx))
        form.addRow('Type', self.kind)

        self.path = QLineEdit(source.path)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(button('Browse', self.pick_folder))
        self.detect_btn = button('⚡ Detect EmuDeck', self.detect_emudeck)
        row.addWidget(self.detect_btn)
        form.addRow('Folder', row)

        self.emulator = QLineEdit(source.emulator)
        row_emu = QHBoxLayout()
        row_emu.addWidget(self.emulator, 1)
        row_emu.addWidget(button('Browse', self.pick_emulator))
        form.addRow('Emulator executable', row_emu)

        self.args = QLineEdit(source.args_template or '-f -g "{rom}"')
        form.addRow('Launch arguments', self.args)

        self.extensions = QLineEdit(source.extensions or '.nsp, .xci, .nro')
        form.addRow('File extensions', self.extensions)

        self.enabled = QCheckBox('Include in scans')
        self.enabled.setChecked(source.enabled)
        form.addRow('', self.enabled)
        layout.addLayout(form)

        self.hint = label('', 'muted', True)
        layout.addWidget(self.hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Save folder')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancel')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.kind.currentIndexChanged.connect(self.toggle)
        self.toggle(initial=True)

    def toggle(self, initial=False):
        data = self.kind.currentData()
        is_emu = is_emulator(data)
        self.detect_btn.setVisible(is_emu)
        self.source_form.setRowVisible(2, is_emu)
        self.source_form.setRowVisible(3, is_emu)
        self.source_form.setRowVisible(4, is_emu)
        self.hint.setVisible(is_emu)

        if not initial:
            if data == 'switch_ryujinx':
                if not self.args.text() or self.args.text() == '-f -g "{rom}"':
                    self.args.setText('"{rom}"')
                if not self.extensions.text():
                    self.extensions.setText('.nsp, .xci')
            elif data in {'switch_yuzu', 'eden'}:
                if not self.args.text() or self.args.text() == '"{rom}"':
                    self.args.setText('-f -g "{rom}"')
                if not self.extensions.text():
                    self.extensions.setText('.nsp, .xci, .nro')

        if data == 'switch_ryujinx':
            self.hint.setText('Ryujinx: launch Switch ROMs with "{rom}".\nDLC & update packages are filtered out automatically.')
        elif data in {'switch_yuzu', 'eden'}:
            self.hint.setText('Yuzu / Eden / Suyu: launch Switch ROMs with -f -g "{rom}".\nDLC & update packages are filtered out automatically.')
        elif data == 'custom':
            self.hint.setText('Custom emulator: specify arguments template containing {rom} and comma-separated extensions (e.g. .iso, .chd).')
        self.adjustSize()

    def detect_emudeck(self):
        user_profile = os.environ.get('USERPROFILE', str(Path.home()))
        appdata = os.environ.get('APPDATA', '')

        candidate_roots = [
            Path(user_profile) / 'Emulation',
            Path('C:/Emulation'),
            Path('D:/Emulation'),
            Path('E:/Emulation'),
        ]

        found_roms = None
        for root in candidate_roots:
            switch_roms = root / 'roms' / 'switch'
            if switch_roms.is_dir():
                found_roms = switch_roms
                break

        candidate_emulators = [
            (Path(user_profile) / 'Emulation' / 'emulators' / 'ryujinx' / 'publish' / 'Ryujinx.exe', 'switch_ryujinx', '"{rom}"'),
            (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'ryujinx.bat', 'switch_ryujinx', '"{rom}"'),
            (Path(appdata) / 'EmuDeck' / 'emulators' / 'Ryujinx.exe', 'switch_ryujinx', '"{rom}"'),
            (Path(user_profile) / 'Emulation' / 'emulators' / 'yuzu' / 'yuzu-windows-msvc' / 'yuzu.exe', 'switch_yuzu', '-f -g "{rom}"'),
            (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'yuzu.bat', 'switch_yuzu', '-f -g "{rom}"'),
        ]
        if os.name != 'nt':
            candidate_emulators = [
                (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'ryujinx.sh', 'switch_ryujinx', '"{rom}"'),
                (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'yuzu.sh', 'switch_yuzu', '-f -g "{rom}"'),
                (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'eden.sh', 'switch_yuzu', '-f -g "{rom}"'),
                (Path(user_profile) / 'Emulation' / 'tools' / 'launchers' / 'suyu.sh', 'switch_yuzu', '-f -g "{rom}"'),
            ] + candidate_emulators

        found_emu, detected_kind, detected_args = None, None, None
        for path, kind, args in candidate_emulators:
            if path.is_file():
                found_emu, detected_kind, detected_args = path, kind, args
                break

        if found_roms or found_emu:
            if found_roms:
                self.path.setText(str(found_roms))
            if found_emu:
                self.emulator.setText(str(found_emu))
                idx = self.kind.findData(detected_kind)
                if idx >= 0:
                    self.kind.setCurrentIndex(idx)
                self.args.setText(detected_args)
            QMessageBox.information(self, 'EmuDeck Detected',
                f'Found EmuDeck configuration!\n\nROMs folder: {found_roms or "Not detected"}\nEmulator: {found_emu or "Not detected"}')
        else:
            location = '~/Emulation' if os.name != 'nt' else '%USERPROFILE%\\Emulation or drive roots'
            QMessageBox.information(self, 'EmuDeck Not Found',
                f'EmuDeck was not found in standard locations ({location}).\n\nPlease select your ROMs folder and emulator executable manually.')

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Game folder', self.path.text())
        if path:
            self.path.setText(path)

    def pick_emulator(self):
        filters = 'Executable (*.exe *.bat *.cmd *.sh *.AppImage);;All Files (*)' if os.name != 'nt' else 'Executable (*.exe *.bat *.cmd)'
        path, _ = QFileDialog.getOpenFileName(self, 'Emulator Executable', '', filters)
        if path:
            self.emulator.setText(path)

    def validate(self):
        if not Path(self.path.text()).is_dir():
            QMessageBox.warning(self, 'Folder not found', 'Select an existing game folder.')
            return
        is_emu = is_emulator(self.kind.currentData())
        if is_emu:
            if not Path(self.emulator.text()).is_file():
                QMessageBox.warning(self, 'Emulator not found', 'Select an existing emulator executable.')
                return
            if '{rom}' not in self.args.text():
                QMessageBox.warning(self, 'Invalid arguments', 'Emulator launch arguments must contain {rom}.')
                return
        self.accept()

    def value(self):
        is_emu = is_emulator(self.kind.currentData())
        return Source(
            path=self.path.text(),
            kind=self.kind.currentData(),
            emulator=self.emulator.text() if is_emu else '',
            args_template=self.args.text() if is_emu else '',
            extensions=self.extensions.text() if is_emu else '',
            enabled=self.enabled.isChecked()
        )


class AddGameDialog(QDialog):
    def __init__(self, parent, store):
        super().__init__(parent)
        self.store = store
        self.provider = Providers(store)
        self.worker = None
        self.game = None
        self.sgdb_id = 0
        self.art = {}

        self.setWindowTitle('Add Game Manually')
        self.resize(680, 580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        layout.addWidget(label('Add Game', 'section'))
        layout.addWidget(label('Select a game executable or ROM to add directly to your Steam library.', 'muted', True))

        form = QFormLayout()

        self.exe = QLineEdit()
        self.exe.setPlaceholderText('Path to game executable, launcher, or ROM')
        row_exe = QHBoxLayout()
        row_exe.addWidget(self.exe, 1)
        row_exe.addWidget(button('Browse...', self.pick_exe))
        form.addRow('Executable / ROM', row_exe)

        self.name = QLineEdit()
        self.name.setPlaceholderText('Game title')
        row_name = QHBoxLayout()
        row_name.addWidget(self.name, 1)
        self.find_art_btn = button('Find Artwork', self.search_artwork, primary=True)
        row_name.addWidget(self.find_art_btn)
        form.addRow('Game Title', row_name)

        self.args = QLineEdit()
        self.args.setPlaceholderText('Optional launch arguments')
        form.addRow('Launch Options', self.args)

        self.start_dir = QLineEdit()
        self.start_dir.setPlaceholderText('Working directory (defaults to folder containing the executable)')
        form.addRow('Start In', self.start_dir)

        layout.addLayout(form)

        card, card_layout = panel(QHBoxLayout, 'card')
        self.cover_preview = Cover('No artwork', '')
        self.cover_preview.setFixedSize(180, 110)
        card_layout.addWidget(self.cover_preview)

        art_col = QVBoxLayout()
        self.art_status = label('Artwork: not selected', 'muted', True)
        art_col.addWidget(self.art_status)
        self.sgdb_label = label('SteamGridDB: not matched', 'muted', True)
        art_col.addWidget(self.sgdb_label)

        btn_row = QHBoxLayout()
        self.pick_art_btn = button('Custom artwork...', self.pick_custom_art)
        btn_row.addWidget(self.pick_art_btn)
        btn_row.addStretch()
        art_col.addLayout(btn_row)

        card_layout.addLayout(art_col, 1)
        layout.addWidget(card)

        self.matches_list = QListWidget()
        self.matches_list.setFixedHeight(120)
        self.matches_list.hide()
        self.matches_list.itemDoubleClicked.connect(self.choose_match)
        layout.addWidget(self.matches_list)

        self.status = label('Enter details and click Add to Library.', 'muted', True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Add to Library')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancel')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def pick_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select Game Executable', self.exe.text(), 'Executables & ROMs (*.exe *.sh *.AppImage *.nsp *.xci *.nro *.iso *.chd *.zip);;All Files (*)')
        if path:
            self.exe.setText(path)
            self.start_dir.setText(str(Path(path).parent))
            suggested_name = clean_name(Path(path).stem)
            if not self.name.text().strip():
                self.name.setText(suggested_name)
            if self.provider.key:
                self.search_artwork()

    def search_artwork(self):
        query = self.name.text().strip()
        if not query:
            self.status.setText('Enter a game title first.')
            return
        if not self.provider.key:
            self.status.setText('SteamGridDB API key is not configured in Settings.')
            return
        if self.worker:
            return
        self.status.setText(f'Searching SteamGridDB for "{query}"...')
        self.find_art_btn.setEnabled(False)

        def work(cancel, progress):
            matches = self.provider.search(query, cancel=cancel)
            from .providers import smart_match
            match = smart_match(matches, query)
            art_set = {}
            if match:
                dummy_game = Game(name=match['name'], exe=self.exe.text(), sgdb_id=match['id'])
                self.provider.artwork_set(dummy_game, cancel=cancel, progress=progress, replace=True)
                art_set = dummy_game.art
            return matches, match, art_set

        def done(result):
            matches, match, art_set = result
            self.find_art_btn.setEnabled(True)
            if match:
                self.sgdb_id = match['id']
                self.art = art_set
                self.sgdb_label.setText(f'SteamGridDB: #{match["id"]} · {match["name"]}')
                self.art_status.setText(f'Artwork: {len(self.art)}/5 downloaded')
                landscape = self.art.get('landscape') or self.art.get('hero') or self.art.get('portrait')
                if landscape:
                    from PySide6.QtGui import QPixmap
                    self.cover_preview.pixmap = QPixmap(landscape)
                    self.cover_preview.update()
                self.status.setText(f'Matched: {match["name"]}. Artwork ready!')
                self.matches_list.hide()
            elif matches:
                self.matches_list.clear()
                for m in matches:
                    item = QListWidgetItem(f'{m["name"]}  ·  #{m["id"]}')
                    item.setData(Qt.UserRole, m)
                    self.matches_list.addItem(item)
                self.matches_list.show()
                self.status.setText(f'Found {len(matches)} matches. Double-click the correct game above.')
            else:
                self.status.setText('No matches found on SteamGridDB. You can set custom artwork below.')

        def failed(error):
            self.find_art_btn.setEnabled(True)
            self.status.setText(f'Search error: {error}')

        self.worker = Worker(work, self)
        self.worker.result.connect(done)
        self.worker.failed.connect(failed)
        self.worker.finished.connect(lambda: setattr(self, 'worker', None))
        self.worker.start()

    def choose_match(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        self.name.setText(data['name'])
        self.matches_list.hide()
        self.search_artwork()

    def pick_custom_art(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select Cover Image', '', 'Images (*.png *.jpg *.jpeg *.webp *.ico)')
        if path:
            try:
                cached = self.provider.local_image(path)
                self.art['landscape'] = cached
                from PySide6.QtGui import QPixmap
                self.cover_preview.pixmap = QPixmap(cached)
                self.cover_preview.update()
                self.art_status.setText('Custom cover selected.')
            except Exception as e:
                self.status.setText(str(e))

    def save(self):
        exe_path = self.exe.text().strip('"')
        title = self.name.text().strip()
        if not title:
            QMessageBox.warning(self, 'Missing Title', 'Please enter a game title.')
            return
        if not exe_path or not Path(exe_path).is_file():
            QMessageBox.warning(self, 'Missing Executable', 'Please select a valid executable or ROM file.')
            return

        working_dir = self.start_dir.text().strip('"') or str(Path(exe_path).parent)
        is_rom = Path(exe_path).suffix.casefold() in {'.nsp', '.xci', '.nro', '.iso', '.chd', '.rvz'}
        self.game = Game(
            name=title,
            exe=exe_path,
            args=self.args.text().strip(),
            start_dir=working_dir,
            kind='custom' if is_rom else 'pc',
            confidence=100,
            selected=True,
            pending=True,
            sgdb_id=self.sgdb_id,
            art=dict(self.art),
            reasons=['Manually added game']
        )
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, parent, store):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('NSLM settings')
        self.resize(740, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(label('Settings', 'section'))
        tabs = QTabWidget()
        layout.addWidget(tabs)
        steam_page = QWidget()
        form = QFormLayout(steam_page)
        form.setContentsMargins(22, 26, 22, 22)
        self.path = QLineEdit(store.settings.get('steam') or steam.discover_steam())
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(button('Browse', self.pick_steam))
        form.addRow('Steam folder', row)
        self.profile = QComboBox()
        form.addRow('Profile', self.profile)
        self.restart = QCheckBox('Start Steam after restoring a backup')
        self.restart.setChecked(store.settings.get('restart', True))
        form.addRow(self.restart)
        form.addRow(label('After adding games, NSLM leaves Steam closed and offers a Launch Steam button.', 'muted', True))
        self.remote_enabled = QCheckBox('Include Remote Play shortcuts from another PC')
        self.remote_enabled.setChecked(store.settings.get('remote_play_enabled', False))
        form.addRow(self.remote_enabled)
        self.remote_shortcuts = QLineEdit(store.settings.get('remote_shortcuts', ''))
        remote_row = QHBoxLayout()
        remote_row.addWidget(self.remote_shortcuts)
        self.remote_browse = button('Browse', self.pick_remote_shortcuts)
        remote_row.addWidget(self.remote_browse)
        form.addRow('Remote shortcut file', remote_row)
        self.remote_note = label(
            'Choose a copied shortcuts.vdf from the PC that hosts your Remote Play games. '
            'NSLM reads it only to recognize cards, then writes artwork only to this Steam profile.',
            'muted', True)
        form.addRow(self.remote_note)
        self.remote_enabled.toggled.connect(self.update_remote_controls)
        self.update_remote_controls(self.remote_enabled.isChecked())
        tabs.addTab(steam_page, 'Steam')
        self.path.editingFinished.connect(self.refresh_profiles)
        self.refresh_profiles()
        self.profile.setCurrentIndex(max(0, self.profile.findData(store.settings.get('profile', ''))))
        art_page = QWidget()
        art = QVBoxLayout(art_page)
        art.setContentsMargins(22, 26, 22, 22)
        art.addWidget(label('SteamGridDB', 'section'))
        art.addWidget(label('Enter your SteamGridDB API key to download artwork.\nSign in on the website with Steam to get a free key.', 'muted', True))
        art.addWidget(button('Get API key', lambda: QDesktopServices.openUrl(QUrl('https://www.steamgriddb.com/profile/preferences/api'))))
        self.sgdb = QLineEdit(store.secret('sgdb_key'))
        self.sgdb.setEchoMode(QLineEdit.Password)
        self.sgdb.setPlaceholderText('SteamGridDB API key')
        art.addWidget(self.sgdb)
        protection_note = 'The key is encrypted for your Windows account.' if os.name == 'nt' else 'The key is stored in NSLM\'s local application data on this device.'
        art.addWidget(label(protection_note, 'muted', True))
        art.addStretch()
        tabs.addTab(art_page, 'Artwork')
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Save settings')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancel')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh_profiles(self):
        selected = self.profile.currentData()
        self.profile.clear()
        for value, name in steam.profiles(self.path.text()):
            self.profile.addItem(f'{name}  ·  {value}', value)
        if selected:
            self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))

    def pick_steam(self):
        path = QFileDialog.getExistingDirectory(self, 'Steam folder', self.path.text())
        if path:
            self.path.setText(path)
            self.refresh_profiles()

    def pick_remote_shortcuts(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose copied Remote Play shortcuts.vdf', self.remote_shortcuts.text(),
            'Steam shortcuts (shortcuts.vdf);;All files (*)')
        if path:
            self.remote_shortcuts.setText(path)

    def update_remote_controls(self, enabled):
        self.remote_shortcuts.setEnabled(enabled)
        self.remote_browse.setEnabled(enabled)
        self.remote_note.setEnabled(enabled)

    def save(self):
        try:
            config = steam.config_path(self.path.text(), self.profile.currentData() or '')
            remote_path = self.remote_shortcuts.text().strip()
            if self.remote_enabled.isChecked():
                if not remote_path:
                    raise ValueError('Choose the copied shortcuts.vdf file for Remote Play games, or turn off Remote Play shortcuts.')
                # Validate the selected binary now. This is read-only and
                # prevents a settings change that would hide the library later.
                steam.remote_library(remote_path, config)
            self.store.settings.update(
                steam=self.path.text(), profile=self.profile.currentData(), auto_scan=False,
                restart=self.restart.isChecked(), remote_play_enabled=self.remote_enabled.isChecked(),
                remote_shortcuts=remote_path)
            self.store.set_secret('sgdb_key', self.sgdb.text().strip())
            self.store.save()
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, 'Save failed', str(error))


class GameDialog(QDialog):
    def __init__(self, parent, game, store):
        super().__init__(parent)
        self.game = copy.deepcopy(game)
        self.original_exe = game.exe
        self.provider = Providers(store)
        self.worker = None
        self.gallery_pages = {kind: 0 for kind in ART_TYPES}
        self.gallery_seen = {kind: set() for kind in ART_TYPES}
        self.gallery_queued = {kind: [] for kind in ART_TYPES}
        self.gallery_batch_size = 8
        self.setWindowTitle('Edit game · ' + game.name)
        self.resize(940, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.addWidget(label('Game details', 'section'))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        launch = QWidget()
        form = QFormLayout(launch)
        form.setContentsMargins(20, 24, 20, 20)
        self.name = QLineEdit(game.name)
        form.addRow('Name', self.name)
        self.exe = QComboBox()
        self.exe.setEditable(True)
        self.exe.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.exe.setMinimumContentsLength(24)
        self.exe.addItems(list(dict.fromkeys([game.exe] + game.alternatives)))
        row = QHBoxLayout()
        row.addWidget(self.exe, 1)
        row.addWidget(button('Browse', self.pick_exe))
        form.addRow('Executable', row)
        self.args = QLineEdit(game.args)
        form.addRow('Arguments', self.args)
        self.start_dir = QLineEdit(game.start_dir or str(Path(game.exe).parent))
        form.addRow('Start in', self.start_dir)
        form.addRow('Detection', label('\n'.join(game.reasons) or 'Existing Steam shortcut', 'muted', True))
        self.tabs.addTab(launch, 'Launch')
        search_page = QWidget()
        search = QVBoxLayout(search_page)
        search.setContentsMargins(20, 20, 20, 20)
        search.addWidget(label('Search SteamGridDB', 'section'))
        row = QHBoxLayout()
        self.query = QLineEdit(game.name)
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query)
        row.addWidget(button('Search', self.search, True))
        search.addLayout(row)
        self.matches = QListWidget()
        self.matches.itemDoubleClicked.connect(self.choose_match)
        search.addWidget(self.matches, 1)
        search.addWidget(button('Use selected game', self.choose_match))
        self.match_label = label(f'SteamGridDB ID: {game.sgdb_id}' if game.sgdb_id else 'No match selected', 'muted')
        search.addWidget(self.match_label)
        self.tabs.addTab(search_page, 'Match game')
        art_page = QWidget()
        art_layout = QVBoxLayout(art_page)
        row = QHBoxLayout()
        self.auto_art_button = button('Auto-fill best set', self.auto_art, True)
        self.auto_art_button.setToolTip('Downloads the best available image for every artwork type. It does not change Steam until you save and use Add / update.')
        row.addWidget(self.auto_art_button)
        self.download_all_button = button('Cache every variant…', self.download_all)
        self.download_all_button.setToolTip('Downloads every available variant to the local NSLM cache. Usually unnecessary: the first choices are loaded automatically.')
        row.addWidget(self.download_all_button)
        art_layout.addLayout(row)
        self.art_tabs = QTabWidget()
        art_layout.addWidget(self.art_tabs, 1)
        self.galleries, self.previews = {}, {}
        self.art_tab_kinds = list(ART_TYPES)
        for kind, title in ART_TYPES.items():
            page = QWidget()
            content = QVBoxLayout(page)
            preview = label('No artwork selected', 'muted')
            preview.setWordWrap(True)
            preview.setAlignment(Qt.AlignCenter)
            preview.setMinimumHeight(108)
            preview.setStyleSheet('background: #202224; border: 1px solid #3a3d40; border-radius: 8px; padding: 5px;')
            content.addWidget(preview)
            self.previews[kind] = preview
            selected = label('No artwork selected', 'muted')
            content.addWidget(selected)
            if not hasattr(self, 'selected_art_labels'):
                self.selected_art_labels = {}
            self.selected_art_labels[kind] = selected
            gallery = QListWidget()
            gallery.setViewMode(QListWidget.IconMode)
            gallery.setResizeMode(QListWidget.Adjust)
            gallery.setMovement(QListWidget.Static)
            gallery.setIconSize(QSize(142, 106))
            gallery.setSpacing(8)
            gallery.itemDoubleClicked.connect(lambda item, k=kind: self.choose_art(k, item))
            self.galleries[kind] = gallery
            content.addWidget(gallery, 1)
            row = QHBoxLayout()
            row.addWidget(button('Load more', lambda _=False, k=kind: self.load_gallery(k)))
            row.addWidget(button('Select', lambda _=False, k=kind: self.choose_art(k, self.galleries[k].currentItem())))
            row.addWidget(button('From file...', lambda _=False, k=kind: self.pick_art(k)))
            content.addLayout(row)
            self.art_tabs.addTab(page, title)
        art_layout.addWidget(label('Double-click an image to select it. The gallery shows static artwork.', 'muted', True))
        self.tabs.addTab(art_page, 'Artwork')
        self.tabs.currentChanged.connect(self.on_main_tab_changed)
        self.art_tabs.currentChanged.connect(lambda _: self.load_current_gallery())
        self.status = label('Use Add / update in the main window to apply these changes to Steam.', 'muted', True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button('Cancel', self.reject))
        row.addWidget(button('Save changes', self.save, True))
        layout.addLayout(row)
        self.refresh_art()
        # Existing Steam shortcuts often predate NSLM's saved gallery match.
        # Resolve that mapping quietly, but never overwrite their current art.
        if self.game.existing and not self.game.sgdb_id:
            QTimer.singleShot(0, self.resolve_existing_match)

    def busy(self, fn, done):
        if self.worker:
            return
        self.tabs.setEnabled(False)
        self.worker = Worker(fn, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.result.connect(done)
        self.worker.failed.connect(lambda error: self.status.setText(str(error)))
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def finished_work(self):
        self.tabs.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None

    def reject(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText('Cancelling download... Close this window when the download stops.')
            return
        super().reject()

    def pick_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Game executable', self.exe.currentText(), 'Executable (*.exe *.sh *.AppImage);;All Files (*)')
        if path:
            self.exe.setCurrentText(path)
            self.start_dir.setText(str(Path(path).parent))

    def search(self):
        query = self.query.text().strip()
        if not query:
            return
        def done(items):
            self.matches.clear()
            for item in items:
                row = QListWidgetItem(f'{item["name"]}   ·   #{item["id"]}')
                row.setData(Qt.UserRole, item)
                self.matches.addItem(row)
            self.status.setText(f'Matches: {len(items)}. Select the correct game.')
        self.busy(lambda cancel, progress: self.provider.search(query, cancel), done)

    def choose_match(self, *_):
        row = self.matches.currentItem()
        if row:
            data = row.data(Qt.UserRole)
            if self.game.sgdb_id != data['id']:
                # A match selects a gallery, not a replacement artwork set.
                # Keep the user's current Cover/Grid/Hero/Logo/Icon intact.
                for gallery in self.galleries.values():
                    gallery.clear()
                self.gallery_pages = {k: 0 for k in ART_TYPES}
                self.gallery_seen = {k: set() for k in ART_TYPES}
                self.gallery_queued = {k: [] for k in ART_TYPES}
            self.game.sgdb_id = data['id']
            self.game.name = data['name']
            self.name.setText(data['name'])
            self.match_label.setText(f'{data["name"]} · SteamGridDB #{data["id"]}')
            self.refresh_art()
            artwork_was_open = self.tabs.currentIndex() == 2
            self.tabs.setCurrentIndex(2)
            if artwork_was_open:
                self.load_current_gallery()

    def auto_art(self):
        self.game.name = self.name.text().strip()
        self.start_artwork_download(replace=False, preload=True)

    def start_artwork_download(self, replace=False, preload=True):
        """Fill the best set, then make the first gallery choices available at once."""
        if self.worker:
            return

        def work(cancel, progress):
            updated = copy.deepcopy(self.game)
            self.provider.artwork_set(updated, cancel, progress, replace=replace)
            updated.pending = True
            initial = {}
            if preload:
                for kind in ART_TYPES:
                    try:
                        progress(f'Loading {ART_TYPES[kind].lower()} choices…')
                        items = self.provider.gallery_variants(updated, kind, 0, cancel)
                        selected_url = updated.art_sources.get(kind, '')
                        items.sort(key=lambda item: item.get('url') != selected_url)
                        visible, queued = items[:self.gallery_batch_size], items[self.gallery_batch_size:]
                        previews = []
                        for index, item in enumerate(visible):
                            progress(f'Loading {ART_TYPES[kind].lower()} choices {index + 1}/{len(visible)}')
                            previews.append((item, self.provider.download(item.get('thumb') or item['url'], cancel)))
                        initial[kind] = (previews, queued, 1)
                    except InterruptedError:
                        raise
                    except Exception as error:
                        initial[kind] = ([], [], 0)
                        updated.note += ('; ' if updated.note else '') + f'{ART_TYPES[kind]} choices: {error}'
            return updated, initial

        def done(result):
            self.game, initial = result
            self.name.setText(self.game.name)
            if self.game.sgdb_id:
                self.match_label.setText(f'Automatic match · SteamGridDB #{self.game.sgdb_id}')
            for kind, (items, queued, next_page) in initial.items():
                self.gallery_queued[kind] = queued
                self.gallery_pages[kind] = next_page
                self.add_gallery_items(kind, items)
            self.refresh_art()
            self.status.setText(self.game.note or 'Artwork ready. Best choices selected; alternatives are ready below.')

        self.busy(work, done)

    def resolve_existing_match(self):
        """Find a gallery match for an existing shortcut without downloading art."""
        if self.worker or self.game.sgdb_id:
            return
        def work(cancel, progress):
            updated = copy.deepcopy(self.game)
            progress('Finding the matching game for its current artwork…')
            self.provider.sgdb_match(updated, cancel)
            return updated
        def done(updated):
            self.game = updated
            if self.game.sgdb_id:
                self.match_label.setText(f'Automatic match · SteamGridDB #{self.game.sgdb_id}')
                self.status.setText('Artwork mapping ready. Existing artwork was not changed.')
                self.load_current_gallery()
            else:
                self.status.setText('Existing artwork is shown above. No SteamGridDB match was found automatically.')
            self.refresh_art()
        self.busy(work, done)

    def on_main_tab_changed(self, index):
        if index == 2:
            self.load_current_gallery()

    def load_current_gallery(self):
        """Load the first choices for only the artwork type the user opened."""
        if self.tabs.currentIndex() != 2 or self.worker:
            return
        kind = self.art_tab_kinds[self.art_tabs.currentIndex()]
        if self.galleries[kind].count() or self.gallery_queued[kind] or self.gallery_pages[kind]:
            return
        self.load_gallery(kind)

    def refresh_art(self):
        for kind, preview in self.previews.items():
            path = self.game.art.get(kind, '')
            if path:
                from PySide6.QtGui import QPixmap
                preview.setPixmap(QPixmap(path).scaled(200, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                preview.setToolTip('Current artwork')
                source = self.game.art_sources.get(kind)
                if source and 'steamgriddb.com' in source:
                    selected_text = '✓ Selected from SteamGridDB'
                elif source and 'steamstatic.com' in source:
                    selected_text = '✓ Current official Steam artwork'
                elif self.game.existing:
                    selected_text = '✓ Current Steam artwork'
                else:
                    selected_text = '✓ Selected custom artwork'
                self.selected_art_labels[kind].setText(selected_text)
            else:
                preview.clear()
                preview.setText('No artwork selected')
                self.selected_art_labels[kind].setText('No artwork selected')
            self.mark_selected_art(kind)
        # On Wayland, a pixmap changed while its tab is visible can remain
        # cached until Qt receives another tab-change event.  Request a second
        # paint on the next event-loop turn so the chosen best artwork appears
        # immediately, without the user having to switch tabs away and back.
        self.repaint_visible_artwork()
        QTimer.singleShot(0, self.repaint_visible_artwork)

    def repaint_visible_artwork(self):
        if not hasattr(self, 'art_tabs'):
            return
        page = self.art_tabs.currentWidget()
        if page:
            page.updateGeometry()
            page.update()
        self.art_tabs.update()

    def mark_selected_art(self, kind):
        selected_url = self.game.art_sources.get(kind, '')
        selected_item = None
        for index in range(self.galleries[kind].count()):
            item = self.galleries[kind].item(index)
            data = item.data(Qt.UserRole) or {}
            is_selected = bool(selected_url and data.get('url') == selected_url)
            author = data.get('author', {}).get('name', '')[:22]
            item.setText(('✓ ' if is_selected else '') + author)
            if is_selected:
                selected_item = item
        if selected_item:
            self.galleries[kind].setCurrentItem(selected_item)

    def add_gallery_items(self, kind, items):
        for item, image in items:
            if item['id'] in self.gallery_seen[kind]:
                continue
            self.gallery_seen[kind].add(item['id'])
            row = QListWidgetItem(QIcon(image), item.get('author', {}).get('name', '')[:22])
            row.setData(Qt.UserRole, item)
            row.setToolTip(f'{item.get("width", "?")} × {item.get("height", "?")} · {item.get("author", {}).get("name", "")}')
            self.galleries[kind].addItem(row)
        self.mark_selected_art(kind)

    def load_gallery(self, kind):
        def work(cancel, progress):
            updated = copy.deepcopy(self.game)
            if self.gallery_queued[kind]:
                items, queued, next_page = self.gallery_queued[kind][:self.gallery_batch_size], self.gallery_queued[kind][self.gallery_batch_size:], self.gallery_pages[kind]
            else:
                page = self.gallery_pages[kind]
                page_items = self.provider.gallery_variants(updated, kind, page, cancel)
                items, queued, next_page = page_items[:self.gallery_batch_size], page_items[self.gallery_batch_size:], page + 1
            result = []
            for index, item in enumerate(items):
                progress(f'Loading variants {index + 1}/{len(items)}')
                image = self.provider.download(item.get('thumb') or item['url'], cancel)
                result.append((item, image))
            return result, queued, next_page, updated.sgdb_id
        def done(result):
            items, queued, next_page, sgdb_id = result
            if sgdb_id:
                self.game.sgdb_id = sgdb_id
                self.match_label.setText(f'Automatic match · SteamGridDB #{sgdb_id}')
            self.gallery_queued[kind] = queued
            self.gallery_pages[kind] = next_page
            self.add_gallery_items(kind, items)
            self.status.setText('Official Steam choices are first; SteamGridDB choices follow.' if items else 'No more variants.')
        self.busy(work, done)

    def choose_art(self, kind, item):
        if item is None:
            return
        data = item.data(Qt.UserRole)
        def done(path):
            self.game.art[kind] = path
            self.game.art_sources[kind] = data['url']
            self.refresh_art()
            self.status.setText(ART_TYPES[kind] + ': image selected.')
        self.busy(lambda cancel, progress: self.provider.download(data['url'], cancel), done)

    def pick_art(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose image', '', 'Images (*.png *.jpg *.jpeg *.webp *.ico)')
        if path:
            try:
                self.game.art[kind] = self.provider.local_image(path)
                self.game.art_sources.pop(kind, None)
                self.refresh_art()
            except Exception as error:
                self.status.setText(str(error))

    def download_all(self):
        answer = QMessageBox.question(
            self, 'Cache every variant?',
            'This downloads every official Steam and SteamGridDB artwork variant for this game into NSLM\'s local cache.\n\n'
            'It does not change Steam and is usually unnecessary: the best set and first choices are already loaded.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        def work(cancel, progress):
            count = 0
            for kind in ART_TYPES:
                seen, page = set(), 0
                while True:
                    items = self.provider.gallery_variants(self.game, kind, page, cancel)
                    fresh = [item for item in items if item['id'] not in seen]
                    if not fresh:
                        break
                    for item in fresh:
                        seen.add(item['id'])
                        progress(f'{ART_TYPES[kind]} · variants downloaded: {count}')
                        self.provider.download(item['url'], cancel)
                        count += 1
                    page += 1
            return count
        self.busy(work, lambda count: self.status.setText(f'Cached {count} variants locally. Steam is unchanged until you save and use Add / update.'))

    def save(self):
        if self.worker:
            return
        executable = self.exe.currentText().strip('"')
        if not self.name.text().strip() or (not Path(executable).is_file() and not (self.game.existing and executable == self.original_exe)):
            self.status.setText('Enter a name and select an existing executable.')
            return
        self.game.name = self.name.text().strip()
        self.game.exe = self.exe.currentText().strip('"')
        self.game.args = self.args.text()
        self.game.start_dir = self.start_dir.text().strip('"')
        self.game.confidence = 100
        self.game.selected = True
        self.game.pending = True
        self.accept()
