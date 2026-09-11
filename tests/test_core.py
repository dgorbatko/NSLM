import copy
import hashlib
import json
import re
import struct
import threading
import zipfile
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from shelf import steam, vdf
from shelf.models import Game, Source, clean_name
from shelf.app import matching_existing, needs_launcher_repair
from shelf.scanner import scan
from shelf.storage import Store, protect, data_dir
from shelf.providers import Providers, exact_match, smart_match, search_names, title_queries
from shelf.models import is_emulator


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / 'Steam'
    root.mkdir()
    (root / 'steam.exe').write_bytes(b'fixture')
    config = root / 'userdata' / '123' / 'config'
    config.mkdir(parents=True)
    exe = tmp_path / 'My Game' / 'Game.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'fixture')
    monkeypatch.setattr(steam, 'running', lambda: [])
    monkeypatch.setattr(steam, 'shutdown', Mock(return_value=False))
    monkeypatch.setattr(steam, 'restart', Mock())
    return root, config, exe


def test_binary_roundtrip_preserves_fields_and_types():
    nodes = [vdf.Node(0, 'shortcuts', [vdf.Node(0, '0', [vdf.Node(1, 'AppName', 'Игра 日本語'),
        vdf.Node(2, 'appid', 4294967295), vdf.Node(3, 'FutureFloat', b'\x00\x00\xc0\x7f'),
        vdf.Node(7, 'WideID', b'12345678'), vdf.Node(0, 'tags', [vdf.Node(1, '0', 'Мои игры')])])])]
    binary = vdf.dumps(nodes)
    assert vdf.dumps(vdf.loads(binary)) == binary


@pytest.mark.parametrize('data', [b'', b'\0shortcuts\0', b'\x01name\0bad', b'\x0cunknown\0\x08', b'\x08extra'])
def test_reject_corrupt_binary(data):
    with pytest.raises(ValueError):
        vdf.loads(data)


def test_insert_then_skip_then_update_preserves_unknown(fixture):
    root, config, exe = fixture
    game = Game('My Game', str(exe))
    binary, _, changes, _ = steam.prepare(config, [game])
    (config / 'shortcuts.vdf').write_bytes(binary)
    tree = vdf.loads(binary)
    entry = vdf.shortcuts(tree).value[0]
    entry.set('LastPlayTime', 777, 2)
    entry.set('UnknownFutureField', 'retain me')
    entry.set('tags', [vdf.Node(1, '0', 'Favorites')], 0)
    (config / 'shortcuts.vdf').write_bytes(vdf.dumps(tree))
    skipped_binary, _, changes, skipped = steam.prepare(config, [game])
    assert changes == [] and skipped == ['My Game']
    assert skipped_binary == vdf.dumps(tree)
    game.name = 'Renamed'
    updated, _, changes, _ = steam.prepare(config, [game], overwrite=True)
    edited = vdf.shortcuts(vdf.loads(updated)).value[0]
    assert edited.get('LastPlayTime') == 777
    assert edited.get('UnknownFutureField') == 'retain me'
    assert edited.get('appid') == entry.get('appid')
    assert edited.get('tags')[0].value == 'Favorites'
    assert edited.get('AppName') == 'Renamed'


def test_remote_play_library_reads_pc_shortcuts_but_uses_deck_artwork(fixture, tmp_path):
    root, config, exe = fixture
    pc_shortcuts = tmp_path / 'PC-shortcuts.vdf'
    binary, _, changes, _ = steam.prepare(config, [Game('Remote game', str(exe))])
    pc_shortcuts.write_bytes(binary)
    appid = changes[0][1]
    (config / 'grid').mkdir()
    deck_cover = config / 'grid' / f'{appid}p.png'
    deck_cover.write_bytes(b'deck-art')

    games = steam.remote_library(pc_shortcuts, config)

    assert len(games) == 1
    assert games[0].remote and games[0].existing
    assert games[0].appid == appid
    assert games[0].art == {'portrait': str(deck_cover.resolve())}


def test_remote_play_apply_writes_artwork_without_creating_a_shortcut(fixture, tmp_path):
    root, config, _exe = fixture
    image = tmp_path / 'cover.png'
    Image.new('RGB', (24, 36), 'red').save(image)
    game = Game('Remote game', r'C:\\Games\\Remote.exe', appid=123456789,
                existing=True, remote=True, art={'portrait': str(image)})

    result = steam.apply(root, '123', [game], tmp_path / 'backups', launch=False)

    assert result['changed'] == [('Remote game', 123456789)]
    assert not (config / 'shortcuts.vdf').exists()
    assert (config / 'grid' / '123456789p.png').read_bytes().startswith(b'\x89PNG')


def test_batch_duplicates_and_eden_same_title(fixture):
    root, config, exe = fixture
    games = [Game('Switch Game', str(exe), '-g "a.nsp"'), Game('Switch Game', str(exe), '-g "b.nsp"')]
    binary, _, changes, _ = steam.prepare(config, games + [games[0]])
    entries = vdf.shortcuts(vdf.loads(binary)).value
    assert len(entries) == 2
    assert entries[0].get('appid') != entries[1].get('appid')


def test_collections_apply_shortcut_tags_and_special_favorites(fixture, tmp_path):
    root, config, exe = fixture
    (config / 'localconfig.vdf').write_text(
        '"UserLocalConfigStore"\n{\n\t"user-collections"\t\t"{\\"favorite\\":{\\"id\\":\\"favorite\\",\\"added\\":[],\\"removed\\":[]}}"\n}\n',
        'utf-8')
    existing = Game('Switch game', str(exe), '-switch')
    binary, _, _, _ = steam.prepare(config, [existing], tags=['SWITCH'])
    (config / 'shortcuts.vdf').write_bytes(binary)
    assert steam.collections(config) == [('Favorites', 'favorite'), ('Switch', 'SWITCH')]

    game = Game('My game', str(exe), '-new')
    result = steam.apply(root, '123', [game], tmp_path / 'backups', launch=False,
                         collections=['Favorites', 'Switch'])
    appid = result['changed'][0][1]
    entry = next(item for item in vdf.shortcuts(steam.read_tree(config)).value if item.get('appid') == appid)
    assert set(steam._tags(entry)) == {'NSLM', 'favorite', 'SWITCH'}
    saved = json.loads(re.search(r'"user-collections"\s+"((?:\\.|[^"\\])*)"',
                                 (config / 'localconfig.vdf').read_text('utf-8')).group(1).replace('\\"', '"'))
    assert appid in saved['favorite']['added']
    backup = next((tmp_path / 'backups').glob('*.zip'))
    assert 'localconfig.vdf' in steam.read_backup(backup, '123')


def test_real_crc_vector():
    import zlib
    assert steam.shortcut_id(r'C:\Games\A.exe', 'A') == (zlib.crc32(b'"C:\\Games\\A.exe"A') | 0x80000000)


def test_installed_native_steam_game_is_detected_without_shortcuts(tmp_path):
    root = tmp_path / 'Steam'
    app_dir = root / 'steamapps' / 'common' / 'Fall Guys'
    app_dir.mkdir(parents=True)
    exe = app_dir / 'RunFallGuys.exe'
    exe.write_bytes(b'fixture')
    (root / 'steamapps' / 'appmanifest_1097150.acf').write_text(
        '"AppState" { "appid" "1097150" "name" "Fall Guys" "installdir" "Fall Guys" }', 'utf-8')
    native = steam.installed_native_games(root)
    assert native == [{'name': 'Fall Guys', 'appid': 1097150, 'directory': str(app_dir)}]
    assert steam.native_match(Game('Fall Guys', str(exe)), native)['appid'] == 1097150


def test_linux_steam_discovery_and_xdg_data_dir(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    steam_root = home / '.local' / 'share' / 'Steam'
    (steam_root / 'userdata').mkdir(parents=True)
    monkeypatch.setattr(steam.Path, 'home', lambda: home)
    monkeypatch.delenv('NSLM_DATA', raising=False)
    monkeypatch.delenv('STEAMSHELF_DATA', raising=False)
    monkeypatch.setenv('XDG_DATA_HOME', str(home / '.data'))
    assert steam.discover_steam() == str(steam_root.resolve())
    assert data_dir() == home / '.data' / 'NSLM'


def test_linux_source_scans_executable_without_extension(tmp_path):
    root = tmp_path / 'Native Games'
    game = root / 'Example Native Game' / 'example-game'
    game.parent.mkdir(parents=True)
    game.write_text('#!/bin/sh\nexit 0\n', 'utf-8')
    game.chmod(0o755)
    found, warnings = scan([Source(str(root), kind='linux_pc')], threading.Event())
    assert not warnings
    assert len(found) == 1
    assert found[0].exe == str(game)
    assert found[0].kind == 'linux_pc'


def test_linux_steam_webhelper_is_treated_as_busy(monkeypatch):
    class Process:
        info = {'name': 'steamwebhelper', 'exe': '/home/deck/.local/share/Steam/ubuntu12_64/steamwebhelper'}

    monkeypatch.setattr(steam.sys, 'platform', 'linux')
    monkeypatch.setattr(steam.psutil, 'process_iter', lambda _: [Process()])
    assert len(steam.running()) == 1


def test_native_match_does_not_guess_between_same_title_games(tmp_path):
    exe = tmp_path / 'Other' / 'FallGuys.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'fixture')
    native = [
        {'name': 'Fall Guys', 'appid': 1, 'directory': str(tmp_path / 'one')},
        {'name': 'Fall Guys', 'appid': 2, 'directory': str(tmp_path / 'two')},
    ]
    assert steam.native_match(Game('Fall Guys', str(exe)), native) is None


def test_backup_restore_roundtrip_and_profile_guard(fixture, tmp_path):
    root, config, exe = fixture
    binary, _, _, _ = steam.prepare(config, [Game('Игра', str(exe))])
    (config / 'shortcuts.vdf').write_bytes(binary)
    (config / 'grid').mkdir()
    (config / 'grid' / 'test.png').write_bytes(b'art')
    original = steam.snapshot_files(config)
    archive = steam.backup(config, tmp_path / 'backups')
    assert steam.read_backup(archive, '123') == original
    with pytest.raises(ValueError, match='different profile'):
        steam.read_backup(archive, '999')
    (config / 'grid' / 'new.png').write_bytes(b'new')
    steam.restore(root, '123', archive, tmp_path / 'backups', launch=False)
    assert steam.snapshot_files(config) == original
    assert len(list((tmp_path / 'backups').glob('*.zip'))) == 2


def test_backup_accepts_steam_artwork_file_links(fixture, tmp_path):
    root, config, _ = fixture
    grid = config / 'grid'
    grid.mkdir()
    target = grid / '2364351193.png'
    alias = grid / '10154811050227138560.png'
    target.write_bytes(b'art')
    try:
        alias.symlink_to(target.name)
    except OSError:
        pytest.skip('Symbolic links are unavailable on this Windows configuration')
    archive = steam.backup(config, tmp_path / 'backups')
    saved = steam.read_backup(archive, '123')
    assert saved.links == {'grid/10154811050227138560.png': 'grid/2364351193.png'}
    steam.restore(root, '123', archive, tmp_path / 'backups', launch=False)
    assert alias.exists() and alias.read_bytes() == b'art'


@pytest.mark.parametrize('name', ['../escape', 'grid/../../escape', 'C:/escape', 'grid\\..\\escape'])
def test_zip_slip_rejected(tmp_path, name):
    archive = tmp_path / 'evil.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('manifest.json', json.dumps({'format': 1, 'profile': '123', 'files': {name: hashlib.sha256(b'bad').hexdigest()}}))
        z.writestr(name, b'bad')
    with pytest.raises(ValueError):
        steam.read_backup(archive, '123')


def test_zip_checksum_rejected(tmp_path):
    archive = tmp_path / 'evil.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('manifest.json', json.dumps({'format': 1, 'profile': '123', 'files': {'grid/a.png': 'invalid'}}))
        z.writestr('grid/a.png', b'bad')
    with pytest.raises(ValueError, match='checksum'):
        steam.read_backup(archive, '123')


def test_commit_normalizes_art_and_removes_old_extension(fixture, tmp_path):
    root, config, exe = fixture
    picture = tmp_path / 'cover.jpg'
    Image.new('RGB', (60, 90), '#778866').save(picture)
    game = Game('Game', str(exe), art={'portrait': str(picture)})
    appid = steam.shortcut_id(str(exe), 'Game')
    (config / 'grid').mkdir()
    (config / 'grid' / f'{appid}p.jpg').write_bytes(b'old')
    (config / 'grid' / 'unrelated.png').write_bytes(b'unrelated')
    result = steam.apply(root, '123', [game], tmp_path / 'backups', launch=False)
    assert result['changed']
    assert (config / 'grid' / f'{appid}p.png').read_bytes().startswith(b'\x89PNG')
    assert not (config / 'grid' / f'{appid}p.jpg').exists()
    assert (config / 'grid' / 'unrelated.png').read_bytes() == b'unrelated'


def test_write_failure_rolls_back(fixture, tmp_path, monkeypatch):
    root, config, exe = fixture
    (config / 'grid').mkdir()
    (config / 'grid' / 'a.png').write_bytes(b'old')
    original = steam.snapshot_files(config)
    real = steam.atomic_write
    calls = 0
    def failing(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('Disk full')
        return real(path, data)
    monkeypatch.setattr(steam, 'atomic_write', failing)
    with pytest.raises(OSError):
        steam.apply(root, '123', [Game('Game', str(exe))], tmp_path / 'backups', launch=False)
    assert steam.snapshot_files(config) == original
    assert not (config / '.nslm.lock').exists()


def test_busy_steam_never_writes(fixture, tmp_path, monkeypatch):
    root, config, exe = fixture
    monkeypatch.setattr(steam, 'shutdown', Mock(side_effect=steam.SteamBusy('busy')))
    with pytest.raises(steam.SteamBusy):
        steam.apply(root, '123', [Game('Game', str(exe))], tmp_path / 'backups')
    assert not (config / 'shortcuts.vdf').exists()
    steam.restart.assert_not_called()


def test_apply_leaves_previously_running_steam_closed_when_launch_is_disabled(fixture, tmp_path, monkeypatch):
    root, _config, exe = fixture
    monkeypatch.setattr(steam, 'running', Mock(side_effect=[[object()], []]))
    result = steam.apply(root, '123', [Game('Game', str(exe))], tmp_path / 'backups', launch=False)
    assert result['changed']
    steam.restart.assert_not_called()


def test_restarted_steam_aborts_commit(fixture, tmp_path, monkeypatch):
    root, config, exe = fixture
    monkeypatch.setattr(steam, 'running', Mock(side_effect=[[], [object()]]))
    with pytest.raises(steam.SteamBusy):
        steam.apply(root, '123', [Game('Game', str(exe))], tmp_path / 'backups', launch=False)
    assert not (config / 'shortcuts.vdf').exists()


def test_linux_restart_uses_a_separate_user_scope(tmp_path, monkeypatch):
    """Steam must not inherit a desktop launcher's application identity."""
    launched = Mock()
    monkeypatch.setattr(steam.sys, 'platform', 'linux')
    monkeypatch.setattr(steam.shutil, 'which', lambda name: {
        'steam': '/usr/bin/steam', 'systemd-run': '/usr/bin/systemd-run',
    }.get(name))
    monkeypatch.setattr(steam.subprocess, 'Popen', launched)
    steam.restart(tmp_path / 'Steam')
    assert launched.call_args.args[0] == [
        '/usr/bin/systemd-run', '--user', '--scope', '--collect', '--no-block', '--quiet', '--', '/usr/bin/steam',
    ]


def test_corrupt_library_is_not_overwritten(fixture, tmp_path):
    root, config, exe = fixture
    (config / 'shortcuts.vdf').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        steam.apply(root, '123', [Game('Game', str(exe))], tmp_path / 'backups', launch=False)
    assert (config / 'shortcuts.vdf').read_bytes() == b'corrupt'


def test_scan_unity_and_unreal_and_exclude_installers(tmp_path):
    root = tmp_path / 'Games'
    unity = root / 'Forest'
    (unity / 'Forest_Data').mkdir(parents=True)
    (unity / 'Forest.exe').write_bytes(b'fake')
    (unity / 'unins000.exe').write_bytes(b'fake')
    unreal = root / 'Adventure'
    (unreal / 'Binaries' / 'Win64').mkdir(parents=True)
    (unreal / 'Binaries' / 'Win64' / 'Adventure-Win64-Shipping.exe').write_bytes(b'fake')
    (unreal / 'Engine').mkdir()
    (unreal / 'Engine' / 'CrashReportClient.exe').write_bytes(b'fake')
    games, warnings = scan([Source(str(root))], threading.Event())
    assert len(games) == 2
    assert {g.name for g in games} == {'Forest', 'Adventure'}
    assert all(g.confidence >= 60 for g in games)
    assert not warnings


def test_scan_excludes_packaged_bootstrapper(tmp_path):
    game = tmp_path / 'Example'
    game.mkdir()
    (game / 'BootstrapPackagedGame.exe').write_bytes(b'fake')
    (game / 'Example.exe').write_bytes(b'fake')
    games, _ = scan([Source(str(tmp_path))], threading.Event())
    assert len(games) == 1
    assert Path(games[0].exe).name == 'Example.exe'


def test_scan_uses_gog_title_instead_of_unreal_bootstrap_metadata(tmp_path, monkeypatch):
    root = tmp_path / 'Games'
    game = root / 'Bang-On Balls Chronicles'
    (game / 'Engine').mkdir(parents=True)
    exe = game / 'BoB.exe'
    exe.write_bytes(b'fake')
    (game / 'goggame-1117332315.info').write_text(json.dumps({
        'name': 'Bang-On Balls: Chronicles',
        'playTasks': [{'category': 'game', 'isPrimary': True, 'name': 'Bang-On Balls: Chronicles'}],
    }), 'utf-8')
    monkeypatch.setattr('shelf.scanner.product_info', lambda _: {'ProductName': 'BootstrapPackagedGame'})
    games, warnings = scan([Source(str(root))], threading.Event())
    assert not warnings and len(games) == 1
    assert games[0].name == 'Bang-On Balls: Chronicles'
    assert Path(games[0].exe).name == 'BoB.exe'
    assert 'BootstrapPackagedGame' not in games[0].search_names
    assert 'Bang-On Balls Chronicles' in games[0].search_names

    # Adding the game directory itself must not split its launcher and binary.
    direct, warnings = scan([Source(str(game))], threading.Event())
    assert not warnings and len(direct) == 1
    assert Path(direct[0].exe).name == 'BoB.exe'


def test_scan_rejects_generic_pe_title_and_uses_folder(tmp_path, monkeypatch):
    root = tmp_path / 'Games'
    game = root / 'Real Game Name'
    game.mkdir(parents=True)
    (game / 'RGN.exe').write_bytes(b'fake')
    monkeypatch.setattr('shelf.scanner.product_info', lambda _: {'ProductName': 'BootstrapPackagedGame'})
    games, _ = scan([Source(str(root))], threading.Event())
    assert len(games) == 1 and games[0].name == 'Real Game Name'


def test_clean_name_removes_invalid_metadata_characters():
    assert clean_name('Disney Dreamlight Valley\x00\ufffd™') == 'Disney Dreamlight Valley'
    assert clean_name('RunFallGuys') == 'Run Fall Guys'


def test_existing_match_accepts_arguments_or_alternate_executable(tmp_path):
    folder = tmp_path / 'Game'
    folder.mkdir()
    scanned_exe = folder / 'Game.exe'
    steam_exe = folder / 'Launcher.exe'
    scanned_exe.write_bytes(b'fake')
    steam_exe.write_bytes(b'fake')
    scanned = Game('Game', str(scanned_exe), source=str(folder), alternatives=[str(steam_exe)])
    existing = Game('Game', str(steam_exe), '--different', existing=True)
    assert matching_existing(scanned, {existing.key: existing}) is existing


def test_scan_ambiguity_not_preselected(tmp_path):
    (tmp_path / 'a.exe').write_bytes(b'fake')
    (tmp_path / 'b.exe').write_bytes(b'fake')
    games, _ = scan([Source(str(tmp_path))], threading.Event())
    assert len(games) == 1 and not games[0].selected
    assert len(games[0].alternatives) == 2


def test_scan_eden_skips_updates_and_dlc(fixture, tmp_path):
    _, _, exe = fixture
    roms = tmp_path / 'Switch'
    roms.mkdir()
    for name in ['Adventure [0100123456780000][v0].nsp', 'Adventure Update.nsp', 'Adventure [0100123456780800].nsp', 'Adventure DLC.nsp']:
        (roms / name).write_bytes(b'fake')
    games, _ = scan([Source(str(roms), 'eden', str(exe))], threading.Event())
    assert len(games) == 1
    assert games[0].name == 'Adventure'
    assert games[0].args.startswith('-f -g "')


def test_cancellation(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        scan([Source(str(tmp_path))], cancel)


def test_missing_folder_warning(tmp_path):
    games, warnings = scan([Source(str(tmp_path / 'missing'))], threading.Event())
    assert not games and warnings


def test_windows_secret_roundtrip():
    value = 'test-not-a-real-api-key'
    encrypted = protect(value)
    assert value not in encrypted
    assert protect(encrypted, decrypt=True) == value


def test_matching_never_picks_sequel_or_ambiguous():
    assert exact_match([{'name': 'Portal 2', 'id': 2}], 'Portal') is None
    assert exact_match([{'name': 'Portal', 'id': 1}, {'name': 'Portal', 'id': 2}], 'Portal') is None
    assert exact_match([{'name': 'Half-Life', 'id': 1}], 'Half Life')['id'] == 1


def test_title_queries_recovers_tales_tails_typo_without_replacing_original():
    assert title_queries('River Tales: Stronger Together') == [
        'River Tales: Stronger Together', 'River Tails: Stronger Together']


def test_title_queries_normalizes_launcher_dash_for_steam_store():
    assert title_queries('River Tails - Stronger Together')[:2] == [
        'River Tails - Stronger Together', 'River Tails: Stronger Together']


def test_provider_requests_five_types_and_partial_failure(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    seen = []
    def assets(game_id, kind, **kwargs):
        seen.append(kind)
        return [] if kind == 'logo' else [{'url': 'https://example.org/a', 'score': 5}]
    monkeypatch.setattr(provider, 'assets', assets)
    monkeypatch.setattr(provider, 'download', lambda *args: 'cached.png')
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: None)
    game = provider.artwork_set(Game('A', 'a.exe', sgdb_id=5), threading.Event(), lambda _: None)
    assert len(seen) == 5 and len(game.art) == 4
    assert 'Logo' in game.note


def test_provider_remembers_selected_steamgriddb_source(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    monkeypatch.setattr(provider, 'assets', lambda *args, **kwargs: [{'url': 'https://example.org/cover.png', 'score': 1}])
    monkeypatch.setattr(provider, 'download', lambda *args, **kwargs: 'cached.png')
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: None)
    game = provider.artwork_set(Game('A', 'a.exe', sgdb_id=5), threading.Event(), lambda _: None)
    assert game.art_sources['portrait'] == 'https://example.org/cover.png'


def test_provider_uses_official_steam_artwork_before_steamgriddb(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    calls = []
    monkeypatch.setattr(provider, 'assets', lambda *args, **kwargs: calls.append(args[1]) or [{'url': 'https://example.org/community.png', 'score': 1}])
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: {'id': 1851610, 'name': 'River Tails: Stronger Together'})
    monkeypatch.setattr(provider, 'steam_store_assets', lambda *args: {})
    monkeypatch.setattr(provider, 'download', lambda url, *args: 'cached-' + url.rsplit('/', 1)[-1])
    game = provider.artwork_set(Game('River Tales: Stronger Together', 'game.exe', sgdb_id=42), threading.Event(), lambda _: None)
    assert game.art['portrait'] == 'cached-library_600x900.jpg'
    assert game.art_sources['portrait'].endswith('/library_600x900.jpg')
    assert len(game.art) == 5
    assert not calls


def test_provider_replaces_older_steamgriddb_fallback_with_official_steam_art(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: {'id': 42, 'name': 'Pratfall'})
    monkeypatch.setattr(provider, 'steam_store_assets', lambda *args: {
        'portrait': ['https://steamstatic.com/official-cover.jpg'],
        'landscape': [], 'hero': [], 'logo': [], 'icon': [],
    })
    monkeypatch.setattr(provider, 'steam_store_urls', lambda *args: [])
    monkeypatch.setattr(provider, 'assets', lambda *args, **kwargs: [])
    monkeypatch.setattr(provider, 'download', lambda url, *_: 'cached-' + url.rsplit('/', 1)[-1])
    game = Game('Pratfall', 'game.exe', art={'portrait': 'old.png'},
                art_sources={'portrait': 'https://www.steamgriddb.com/thumb.png'}, sgdb_id=7)
    provider.artwork_set(game, threading.Event(), lambda _: None)
    assert game.art['portrait'] == 'cached-official-cover.jpg'
    assert game.art_sources['portrait'] == 'https://steamstatic.com/official-cover.jpg'


def test_provider_gallery_lists_official_steam_before_steamgriddb(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    monkeypatch.setattr(provider, 'official_artwork_variants', lambda *args: [
        {'id': 'steam:cover', 'url': 'https://steamstatic.com/cover.jpg', 'author': {'name': 'Official Steam'}},
    ])
    monkeypatch.setattr(provider, 'assets', lambda *args, **kwargs: [
        {'id': 7, 'url': 'https://www.steamgriddb.com/cover.jpg', 'author': {'name': 'Community author'}},
    ])
    game = Game('Pratfall', 'game.exe', sgdb_id=8)
    assert [item['id'] for item in provider.gallery_variants(game, 'portrait')] == ['steam:cover', 7]


def test_provider_uses_hashed_official_assets_when_steamgriddb_is_empty(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    official = {
        'portrait': ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/hash/library_capsule.jpg'],
        'landscape': ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/hash/header.jpg'],
        'hero': ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/hash/library_hero.jpg'],
        'logo': [],
        'icon': ['https://shared.fastly.steamstatic.com/community_assets/images/apps/2802740/icon.jpg'],
    }
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: {'id': 2802740, 'name': 'Heave Ho 2'})
    monkeypatch.setattr(provider, 'steam_store_assets', lambda *args: official)
    monkeypatch.setattr(provider, 'assets', lambda *args, **kwargs: [])
    def download(url, *_):
        if 'logo' in url:
            raise RuntimeError('missing legacy logo')
        return 'cached-' + url.rsplit('/', 1)[-1]
    monkeypatch.setattr(provider, 'download', download)
    game = provider.artwork_set(Game('Heave Ho 2', 'game.exe'), threading.Event(), lambda _: None)
    assert game.art == {
        'portrait': 'cached-library_capsule.jpg',
        'landscape': 'cached-header.jpg',
        'hero': 'cached-library_hero.jpg',
        'icon': 'cached-icon.jpg',
    }
    assert game.note == 'Unavailable: Logo'


def test_hashed_steam_asset_urls_use_public_storebrowse_metadata(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    payload = {
        'response': {'store_items': [{'appid': 2802740, 'success': 1, 'assets': {
            'asset_url_format': 'steam/apps/2802740/${FILENAME}?t=123',
            'library_capsule': 'cover-hash/library_capsule.jpg',
            'library_hero': 'hero-hash/library_hero.jpg',
            'header': 'header-hash/header.jpg',
            'community_icon': 'a' * 40,
        }}]}
    }
    class Response:
        def json(self):
            return payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
    seen = []
    monkeypatch.setattr(provider, 'request', lambda *args, **kwargs: seen.append((args, kwargs)) or Response())
    urls = provider.steam_store_assets(2802740)
    assert urls['portrait'] == ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/cover-hash/library_capsule.jpg?t=123']
    assert urls['landscape'] == ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/header-hash/header.jpg?t=123']
    assert urls['hero'] == ['https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2802740/hero-hash/library_hero.jpg?t=123']
    assert urls['icon'] == ['https://shared.fastly.steamstatic.com/community_assets/images/apps/2802740/' + 'a' * 40 + '.jpg']
    assert seen[0][0][1].endswith('/IStoreBrowseService/GetItems/v1/')


def test_provider_uses_valid_steamgriddb_filters(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    calls = []
    monkeypatch.setattr(provider, 'sgdb', lambda endpoint, params=None, cancel=None: calls.append((endpoint, params)) or [])
    provider.assets(1, 'portrait')
    provider.assets(1, 'icon')
    assert calls[0][1]['dimensions'] == '600x900'
    assert 'mimes' not in calls[0][1]
    assert 'mimes' not in calls[1][1]


def test_art_for_reads_steam_64_bit_artwork_names(tmp_path):
    config = tmp_path / 'config'
    grid = config / 'grid'
    grid.mkdir(parents=True)
    appid = 2364351193
    shortcut64 = ((appid | 0x80000000) << 32) | 0x02000000
    art = grid / f'{shortcut64}.png'
    art.write_bytes(b'image')
    assert steam.art_for(config, appid)['landscape'] == str(art.resolve())


def test_provider_keeps_local_art_unless_replace(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    monkeypatch.setattr(provider, 'assets', lambda *a, **k: [])
    monkeypatch.setattr(provider, 'steam_store_game', lambda *args: None)
    game = provider.artwork_set(Game('A', 'a.exe', art={'portrait': 'manual.png'}, sgdb_id=5), threading.Event(), lambda _: None)
    assert game.art['portrait'] == 'manual.png'


def test_provider_searches_title_hints_and_skips_generic_name(tmp_path, monkeypatch):
    provider = Providers(Store(tmp_path))
    queries = []
    def search(query, cancel=None):
        queries.append(query)
        return [{'name': 'Bang-On Balls: Chronicles', 'id': 42}] if query == 'Bang-On Balls: Chronicles' else []
    monkeypatch.setattr(provider, 'search', search)
    provider.key = 'fixture-key'
    game = Game('BootstrapPackagedGame', 'BoB.exe', search_names=['Bang-On Balls: Chronicles', 'Bang-On Balls Chronicles'])
    result = provider.sgdb_match(game, threading.Event())
    assert queries[0] == 'Bang-On Balls: Chronicles'
    assert result == 42
    assert 'BootstrapPackagedGame' not in search_names(game)


def test_clean_name_removes_release_build_and_rom_size():
    assert clean_name('PEAK.Build.24961053') == 'PEAK'
    assert clean_name('Mario Kart (2.89 GB)') == 'Mario Kart'


def test_scanner_ignores_nested_libraries_and_cracks(tmp_path):
    games = tmp_path / 'Games'
    (games / 'Actual Game').mkdir(parents=True)
    (games / 'Actual Game' / 'ActualGame.exe').write_bytes(b'game')
    for path in ('steamapps/common/Teardown/Teardown.exe', 'Emulation/Tool/Tool.exe', 'Actual Game/Crack/Fake.exe'):
        candidate = games / path
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b'not a game launcher')
    scanned, _ = scan([Source(str(games))], threading.Event())
    assert [game.name for game in scanned] == ['Actual Game']
    assert scanned[0].exe.endswith('ActualGame.exe')


def test_gog_base_game_wins_over_dlc_manifest(tmp_path):
    root = tmp_path / 'Biomutant'
    root.mkdir()
    (root / 'Biomutant.exe').write_bytes(b'game')
    (root / 'goggame-1.info').write_text(json.dumps({'name': 'BIOMUTANT Mercenary DLC'}), 'utf-8')
    (root / 'goggame-2.info').write_text(json.dumps({
        'name': 'Biomutant',
        'playTasks': [{'isPrimary': True, 'category': 'launcher', 'name': 'Launch Biomutant', 'path': 'Biomutant.exe'}],
    }), 'utf-8')
    scanned, _ = scan([Source(str(root))], threading.Event())
    assert len(scanned) == 1
    assert scanned[0].name == 'Biomutant'


def test_legacy_emulator_command_matches_rom_source():
    rom = r'D:\Games\Emulation\Roms\Mario [0100123456789000].nsp'
    scanned = Game('Mario', r'D:\Games\Emulation\Eden\eden.exe', f'-f -g "{rom}"', source=rom, kind='switch_yuzu')
    existing = Game('Mario', r'D:\Games\Emulation\Eden\eden.exe" -f "D:\Games\Emulation\Roms\Mario [0100123456789000].nsp', kind='steam', existing=True)
    assert matching_existing(scanned, {existing.key: existing}) is existing


def test_missing_existing_launcher_is_flagged_only_with_real_replacement(tmp_path):
    replacement = tmp_path / 'Game.exe'
    replacement.write_bytes(b'game')
    existing = Game('Game', str(tmp_path / 'old' / 'Game.exe'), existing=True)
    assert needs_launcher_repair(Game('Game', str(replacement), kind='pc'), existing)
    assert not needs_launcher_repair(Game('Game', str(replacement), kind='switch_yuzu'), existing)


def test_smart_match_subtitles_and_sequels():
    # Subtitle matching
    assert smart_match([{'name': 'The Witcher 3: Wild Hunt', 'id': 1}], 'The Witcher 3')['id'] == 1
    # Never match sequel
    assert smart_match([{'name': 'Portal 2', 'id': 2}], 'Portal') is None
    assert smart_match([{'name': 'Hades II', 'id': 2}], 'Hades') is None
    # Matching identical
    assert smart_match([{'name': 'Cyberpunk 2077', 'id': 5}], 'Cyberpunk 2077')['id'] == 5
    assert smart_match([{'name': 'Filthy Animals | Heist Simulator', 'id': 6}], 'Filthy Animals')['id'] == 6


def test_exact_match_prefers_verified_steam_record():
    matches = [
        {'name': 'Stick It To The Stick Man', 'id': 2, 'types': [], 'verified': True},
        {'name': 'Stick It to the Stickman', 'id': 1, 'types': ['steam'], 'verified': True},
    ]
    assert exact_match(matches, 'Stick It to the Stickman')['id'] == 1


def test_smart_match_uses_first_prefix_result_when_database_has_editions():
    matches = [
        {'name': 'Filthy Animals | Heist Simulator', 'id': 1},
        {'name': 'Filthy Animals | Halloween Heist', 'id': 2},
    ]
    assert smart_match(matches, 'Filthy Animals')['id'] == 1


def test_store_purges_retired_metadata_credentials(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'sources': [], 'igdb_client': 'old', 'igdb_secret': 'encrypted'}), 'utf-8')
    (tmp_path / 'catalog.json').write_text(json.dumps({'x': {'name': 'Game', 'summary': 'old', 'year': '2020', 'genres': 'Action'}}), 'utf-8')
    store = Store(tmp_path)
    assert 'igdb_client' not in store.settings and 'igdb_secret' not in store.settings
    assert set(store.catalog['x']) == {'name'}
    assert 'igdb_client' not in json.loads((tmp_path / 'settings.json').read_text('utf-8'))


def test_is_emulator_helper():
    assert is_emulator('switch_ryujinx')
    assert is_emulator('switch_yuzu')
    assert is_emulator('eden')
    assert is_emulator('custom')
    assert not is_emulator('pc')


def test_scan_switch_ryujinx(fixture, tmp_path):
    _, _, exe = fixture
    roms = tmp_path / 'SwitchRoms'
    roms.mkdir()
    (roms / 'Super Mario [0100000000010000][v0].nsp').write_bytes(b'fake')
    (roms / 'Super Mario Update.nsp').write_bytes(b'fake')
    source = Source(str(roms), 'switch_ryujinx', str(exe), '"{rom}"')
    games, _ = scan([source], threading.Event())
    assert len(games) == 1
    assert games[0].name == 'Super Mario'
    assert games[0].args == f'"{roms / "Super Mario [0100000000010000][v0].nsp"}"'
