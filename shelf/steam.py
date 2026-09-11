from pathlib import Path, PurePosixPath
import contextlib
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import zlib
import psutil
from . import vdf
from .models import Game, identity, normal_path, normalized_title
from .storage import atomic_write

SUFFIXES = {'portrait': 'p', 'landscape': '', 'hero': '_hero', 'logo': '_logo', 'icon': '_icon'}
FAVORITES_TAG = 'favorite'


def discover_steam():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            return winreg.QueryValueEx(key, 'SteamPath')[0]
    except (OSError, ImportError, AttributeError):
        pass
    mac_steam = Path.home() / 'Library/Application Support/Steam'
    if mac_steam.is_dir():
        return str(mac_steam)
    # SteamOS normally exposes all three paths below as aliases.  Prefer the
    # canonical XDG path, but retain the other common Linux locations too.
    for linux_steam in (Path.home() / '.local/share/Steam', Path.home() / '.steam/steam', Path.home() / '.steam/root'):
        if linux_steam.is_dir() and (linux_steam / 'userdata').is_dir():
            return str(linux_steam.resolve())
    return ''


def profiles(steam):
    root = Path(steam) / 'userdata'
    names = {}
    login = Path(steam) / 'config' / 'loginusers.vdf'
    if login.exists():
        for sid, body in re.findall(r'"(\d{17})"\s*\{([^}]+)\}', login.read_text('utf-8', errors='replace')):
            name = re.search(r'"PersonaName"\s*"([^"]*)"', body, re.I)
            names[str(int(sid) - 76561197960265728)] = name[1] if name else sid
    if not root.is_dir():
        return []
    return [(p.name, names.get(p.name, 'Profile ' + p.name)) for p in root.iterdir() if p.is_dir() and p.name.isdigit() and p.name != '0']


def config_path(steam, profile):
    if not profile or not profile.isdigit():
        raise ValueError('Select a Steam profile in Settings')
    root = Path(steam).resolve()
    if sys.platform == 'win32' and not (root / 'steam.exe').is_file():
        raise ValueError('steam.exe was not found in the selected folder')
    elif sys.platform != 'win32' and not ((root / 'steam.exe').is_file() or (root / 'userdata').is_dir()):
        raise ValueError('Steam installation or userdata folder was not found in the selected path')
    config = root / 'userdata' / profile / 'config'
    if not config.parent.is_dir():
        raise ValueError('Steam profile not found. Sign in to Steam first.')
    if not config.resolve().is_relative_to(root / 'userdata'):
        raise ValueError('The profile folder points outside Steam')
    grid = config / 'grid'
    if grid.is_symlink() or grid.is_junction():
        raise ValueError('The grid folder is a directory link. Use a regular folder for writes.')
    return config


def read_tree(config):
    path = Path(config) / 'shortcuts.vdf'
    tree = vdf.loads(path.read_bytes()) if path.exists() else [vdf.Node(0, 'shortcuts', [])]
    vdf.shortcuts(tree)
    return tree


def art_for(config, appid):
    result = {}
    appid = appid & 0xffffffff
    shortcut64 = ((appid | 0x80000000) << 32) | 0x02000000
    for kind, suffix in SUFFIXES.items():
        for candidate_id in (appid, shortcut64):
            for extension in ('.png', '.jpg', '.jpeg', '.webp'):
                path = Path(config) / 'grid' / f'{candidate_id}{suffix}{extension}'
                if path.exists():
                    result[kind] = str(path.resolve())
                    break
            if kind in result:
                break
    return result


def library(config):
    games = []
    for entry in vdf.shortcuts(read_tree(config)).value:
        appid = entry.get('appid', 0)
        game = Game(entry.get('AppName', ''), entry.get('Exe', '').strip('"'), entry.get('LaunchOptions', ''), kind='steam', confidence=100, appid=appid, existing=True, selected=False, art=art_for(config, appid), start_dir=entry.get('StartDir', '').strip('"'))
        games.append(game)
    return games


def _tags(entry):
    """Return a shortcut's tags without assuming that the optional node exists."""
    return [item.value for item in (entry.get('tags', []) or []) if isinstance(item.value, str) and item.value]


def collections(config):
    """List the manual Steam collections usable for non-Steam shortcuts.

    Steam represents ordinary collections as shortcut tags.  Its special
    Favorites collection is named ``favorite`` internally, so expose it with
    the familiar label while retaining the exact tag value on write.
    """
    seen = {}
    for entry in vdf.shortcuts(read_tree(config)).value:
        for tag in _tags(entry):
            if tag.casefold() == 'nslm':
                continue
            label = 'Favorites' if tag.casefold() == FAVORITES_TAG else tag.title()
            seen.setdefault(label.casefold(), (label, tag))
    # Favorites can have no non-Steam shortcut yet, but still exists in the
    # user's Steam profile.  Detect it from the local config without parsing
    # or rewriting that file here.
    local_config = Path(config) / 'localconfig.vdf'
    if local_config.is_file() and re.search(r'(?m)^\s*"user-collections"\s+"', local_config.read_text('utf-8', errors='replace')):
        seen.setdefault('favorites', ('Favorites', FAVORITES_TAG))
    return [seen[key] for key in sorted(seen, key=lambda key: (key != 'favorites', key))]


def collection_tags(config, labels):
    """Map UI labels back to Steam's stored tag spelling."""
    available = {label.casefold(): tag for label, tag in collections(config)}
    return [available[label.casefold()] for label in labels if label.casefold() in available]


def update_favorites(config, appids):
    """Add shortcut IDs to Steam's special Favorites collection atomically.

    Other manual collections live in each shortcut's ``tags`` section.  Steam
    also keeps Favorites in the profile's localconfig VDF as an escaped JSON
    value, which must be updated together with the shortcut tag.
    """
    path = Path(config) / 'localconfig.vdf'
    if not appids:
        return None
    if not path.is_file():
        raise ValueError('Steam Favorites configuration was not found. No files were changed.')
    text = path.read_text('utf-8', errors='surrogateescape')
    match = re.search(r'(?m)^(\s*"user-collections"\s+")((?:\\.|[^"\\])*)("\s*)$', text)
    if not match:
        raise ValueError('Steam Favorites configuration could not be read. No files were changed.')
    try:
        encoded = match.group(2)
        value = json.loads(encoded.replace('\\"', '"').replace('\\\\', '\\'))
        favorite = value.setdefault(FAVORITES_TAG, {'id': FAVORITES_TAG, 'added': [], 'removed': []})
        if not isinstance(favorite, dict) or not isinstance(favorite.get('added', []), list):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Steam Favorites configuration could not be read. No files were changed.') from error
    added = favorite.setdefault('added', [])
    removed = favorite.setdefault('removed', [])
    for appid in appids:
        appid = int(appid) & 0xffffffff
        if appid not in added:
            added.append(appid)
        while appid in removed:
            removed.remove(appid)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    escaped = payload.replace('\\', '\\\\').replace('"', '\\"')
    return (text[:match.start(2)] + escaped + text[match.end(2):]).encode('utf-8', errors='surrogateescape')


def installed_native_games(steam):
    """Read Steam's local install manifests without calling an account API.

    Native Steam games do not occur in shortcuts.vdf, which is why a scanner
    could previously offer the same installed game as a new non-Steam shortcut.
    """
    root = Path(steam)
    libraries = {root}
    folders = root / 'steamapps' / 'libraryfolders.vdf'
    if folders.is_file():
        text = folders.read_text('utf-8', errors='replace')
        for raw_path in re.findall(r'"path"\s*"([^"]+)"', text, re.I):
            path = Path(raw_path.replace('\\\\', '\\'))
            if (path / 'steamapps').is_dir():
                libraries.add(path)
    games = []
    for library_root in libraries:
        for manifest in (library_root / 'steamapps').glob('appmanifest_*.acf'):
            text = manifest.read_text('utf-8', errors='replace')
            name = re.search(r'"name"\s*"([^"]+)"', text, re.I)
            appid = re.search(r'"appid"\s*"(\d+)"', text, re.I)
            directory = re.search(r'"installdir"\s*"([^"]+)"', text, re.I)
            if not name or not appid:
                continue
            install_dir = library_root / 'steamapps' / 'common' / (directory.group(1) if directory else '')
            games.append({
                'name': name.group(1),
                'appid': int(appid.group(1)),
                'directory': str(install_dir),
            })
    return games


def native_match(game, native_games):
    """Match exact title or an executable inside an installed Steam directory."""
    title = normalized_title(game.name)
    exe = normal_path(game.exe)
    matches = []
    for native in native_games:
        try:
            in_directory = Path(exe).is_relative_to(Path(native['directory']).resolve())
        except (OSError, ValueError):
            in_directory = False
        if in_directory or (title and title == normalized_title(native['name'])):
            matches.append(native)
    return matches[0] if len(matches) == 1 else None


def shortcut_id(exe, name):
    return zlib.crc32((f'"{exe.strip(chr(34))}"' + name).encode('utf-8')) | 0x80000000


def running():
    result = []
    # SteamOS can briefly leave steamwebhelper alive while its main launcher
    # is transitioning.  Treat that as busy too: refusing a write is safer
    # than racing Steam's shortcut-file reload.
    names = {'steam.exe'} if sys.platform == 'win32' else {'steam', 'steamwebhelper'}
    for process in psutil.process_iter(['name', 'exe']):
        if (process.info['name'] or '').casefold() in names:
            result.append(process)
    return result


class SteamBusy(RuntimeError):
    pass


def shutdown(steam, force=False, progress=lambda _: None):
    processes = running()
    if not processes:
        return False
    progress('Closing Steam...')
    exe = Path(steam) / 'steam.exe'
    if exe.is_file():
        subprocess.Popen([str(exe), '-shutdown'], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    elif sys.platform == 'darwin':
        subprocess.Popen(['osascript', '-e', 'tell application "Steam" to quit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # On SteamOS this asks the active Steam client, including Gaming Mode,
        # to exit cleanly before its VDF files are touched.
        launcher = shutil.which('steam') or str(Path(steam) / 'steam.sh')
        subprocess.Popen([launcher, '-shutdown'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 25
    while running() and time.monotonic() < deadline:
        time.sleep(.3)
    if running() and not force:
        raise SteamBusy('Steam did not close within 25 seconds. Close your game and Steam, or retry with force-close enabled.')
    if running():
        for process in running():
            try:
                # Never terminate game children or the system Steam service.
                for child in process.children(recursive=True):
                    if child.name().casefold() in {'steamwebhelper.exe', 'gameoverlayui.exe', 'steamwebhelper', 'gameoverlayui'}:
                        child.kill()
                process.kill()
            except psutil.NoSuchProcess:
                pass
        deadline = time.monotonic() + 8
        while running() and time.monotonic() < deadline:
            time.sleep(.2)
    if running():
        raise SteamBusy('Steam is still running. No files were changed.')
    return True


def restart(steam):
    exe = Path(steam) / 'steam.exe'
    if exe.is_file():
        subprocess.Popen([str(exe)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-a', 'Steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        launcher = shutil.which('steam') or str(Path(steam) / 'steam.sh')
        subprocess.Popen([launcher], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Snapshot(dict):
    def __init__(self, *args, links=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.links = links or {}


def artwork_links(config):
    config = Path(config)
    grid = (config / 'grid').resolve()
    links = {}
    for path in tracked_paths(config):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(grid):
                raise ValueError(f'Artwork link points outside the grid folder: {path.name}')
            links[path.relative_to(config).as_posix()] = 'grid/' + target.relative_to(grid).as_posix()
    return links


def tracked_paths(config, include_localconfig=False):
    config = Path(config)
    result = []
    shortcut = config / 'shortcuts.vdf'
    if shortcut.exists():
        result.append(shortcut)
    local_config = config / 'localconfig.vdf'
    if include_localconfig and local_config.exists():
        result.append(local_config)
    grid = config / 'grid'
    if grid.exists():
        for directory, dirs, files in os.walk(grid, followlinks=False):
            for name in dirs:
                path = Path(directory) / name
                if path.is_symlink() or path.is_junction():
                    raise ValueError(f'Linked artwork folders are not supported: {path}')
            for name in files:
                path = Path(directory) / name
                if path.is_symlink():
                    try:
                        target = path.resolve(strict=True)
                    except (OSError, RuntimeError) as error:
                        raise ValueError(f'Broken artwork link: {path.name}') from error
                    if not target.is_file() or not target.is_relative_to(grid.resolve()):
                        raise ValueError(f'Artwork link points outside the grid folder: {path.name}')
                result.append(path)
    return result


def snapshot_files(config, include_localconfig=False):
    return Snapshot({p.relative_to(config).as_posix(): p.read_bytes()
                     for p in tracked_paths(config, include_localconfig)}, links=artwork_links(config))


def fingerprint(config, include_localconfig=False):
    result = {}
    for path in tracked_paths(config, include_localconfig):
        with path.open('rb') as handle:
            result[path.relative_to(config).as_posix()] = hashlib.file_digest(handle, 'sha256').hexdigest()
    return result


def backup(config, destination, progress=lambda _: None, include_localconfig=False):
    hashes = fingerprint(config, include_localconfig)
    links = artwork_links(config)
    manifest = {'format': 2, 'profile': Path(config).parent.name, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': hashes, 'links': links}
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f'NSLM-{manifest["profile"]}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}.zip'
    tmp = path.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            for index, name in enumerate(hashes):
                progress(f'Backing up artwork: {index + 1}/{len(hashes)}')
                archive.write(Path(config) / name, name)
        if fingerprint(config, include_localconfig) != hashes or artwork_links(config) != links:
            raise RuntimeError('Files changed during backup. Try again.')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def read_backup(path, profile):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > 4 * 1024**3:
            raise ValueError('Backup exceeds the supported size')
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Invalid backup')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') not in (1, 2) or manifest.get('profile') != str(profile):
            raise ValueError('Backup belongs to a different profile or uses an unsupported format')
        if set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Archive contents do not match the manifest')
        result = Snapshot()
        for name, expected in manifest['files'].items():
            p = PurePosixPath(name)
            if '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or not (name in {'shortcuts.vdf', 'localconfig.vdf'} or (len(p.parts) >= 2 and p.parts[0] == 'grid')):
                raise ValueError('Unsafe archive path')
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Backup checksum mismatch')
            result[name] = data
        if 'shortcuts.vdf' in result:
            vdf.shortcuts(vdf.loads(result['shortcuts.vdf']))
        for alias, target in manifest.get('links', {}).items():
            if alias not in result or target not in result or not alias.startswith('grid/') or not target.startswith('grid/') or alias == target or target in manifest.get('links', {}):
                raise ValueError('Invalid artwork link in backup')
            if result[alias] != result[target]:
                raise ValueError('Artwork link does not match its target')
            result.links[alias] = target
        return result


def replace_snapshot(config, files):
    config = Path(config)
    current = {p.relative_to(config).as_posix() for p in tracked_paths(config, 'localconfig.vdf' in files)}
    links = getattr(files, 'links', {})
    for name, data in files.items():
        if name in links:
            continue
        # Validate every parent; an archive must never write through a directory link.
        parent = (config / name).parent
        while parent != config:
            if parent.is_symlink() or parent.is_junction():
                raise ValueError(f'Cannot write through linked directory: {parent}')
            parent = parent.parent
        atomic_write(config / name, data)
    for name, target in links.items():
        alias, destination = config / name, config / target
        if alias.is_symlink() and alias.resolve() == destination.resolve():
            continue
        alias.parent.mkdir(parents=True, exist_ok=True)
        temporary = alias.with_name('.shelf-link-' + uuid.uuid4().hex)
        try:
            try:
                temporary.symlink_to(os.path.relpath(destination, alias.parent))
                os.replace(temporary, alias)
            except OSError as error:
                if getattr(error, 'winerror', None) != 1314:
                    raise
                # Portable restoration without Windows symbolic-link privileges.
                atomic_write(alias, files[target])
        finally:
            temporary.unlink(missing_ok=True)
    for name in set(current) - set(files):
        (config / name).unlink(missing_ok=True)


@contextlib.contextmanager
def write_lock(config):
    config.mkdir(parents=True, exist_ok=True)
    path = config / '.nslm.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f'Another NSLM operation is active. If the app previously crashed, remove {path}.') from error
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def prepare(config, games, overwrite=False, tags=()):
    tree = copy.deepcopy(read_tree(config))
    root = vdf.shortcuts(tree)
    by_key = {identity(e.get('Exe', ''), e.get('LaunchOptions', '')): e for e in root.value}
    by_id = {e.get('appid', 0): e for e in root.value}
    occupied = set(by_id)
    changes, skipped, art_updates = [], [], {}
    for game in games:
        entry = by_id.get(game.appid) if game.existing and game.appid else by_key.get(game.key)
        if not game.name.strip() or (not Path(game.exe).is_file() and (entry is None or entry.get('Exe', '').strip('"') != game.exe)):
            raise ValueError(f'Check the name and executable for {game.name}')
        if entry and not overwrite:
            skipped.append(game.name)
            continue
        if entry is None:
            appid = shortcut_id(game.exe, game.name)
            # Eden uses one executable for multiple games. Preserve unique IDs even for same-title ROMs.
            if appid in occupied:
                appid = (zlib.crc32((game.key + game.name).encode()) | 0x80000000)
                while appid in occupied:
                    appid = ((appid + 1) & 0xffffffff) | 0x80000000
            entry = vdf.Node(0, str(len(root.value)), [])
            entry.set('appid', appid, 2)
            for field, value in [('IsHidden', 0), ('AllowDesktopConfig', 1), ('AllowOverlay', 1), ('OpenVR', 0), ('Devkit', 0), ('DevkitOverrideAppID', 0), ('LastPlayTime', 0)]:
                entry.set(field, value, 2)
            for field in ('icon', 'ShortcutPath', 'DevkitGameID', 'FlatpakAppID'):
                entry.set(field, '')
            entry.set('tags', [vdf.Node(1, '0', 'NSLM')], 0)
            root.value.append(entry)
            occupied.add(appid)
        appid = entry.get('appid')
        working_dir = game.start_dir or (entry.get('StartDir', '').strip('"') if entry.get('Exe', '').strip('"') == game.exe else '') or str(Path(game.exe).parent)
        entry.set('AppName', game.name.strip())
        entry.set('Exe', f'"{game.exe.strip(chr(34))}"')
        entry.set('StartDir', f'"{working_dir}"')
        entry.set('LaunchOptions', game.args)
        existing_tags = _tags(entry)
        for tag in tags:
            if tag and tag.casefold() not in {item.casefold() for item in existing_tags}:
                existing_tags.append(tag)
        entry.set('tags', [vdf.Node(1, str(index), tag) for index, tag in enumerate(existing_tags)], 0)
        by_key[game.key] = entry
        by_id[appid] = entry
        for kind, image_path in game.art.items():
            if kind not in SUFFIXES or not Path(image_path).is_file():
                continue
            # Normalize to PNG: no mismatched extensions, malformed images or remote paths at commit.
            from PIL import Image
            import io
            with Image.open(image_path) as picture:
                picture.load()
                if picture.width * picture.height > 50_000_000:
                    raise ValueError('Image is too large')
                output = io.BytesIO()
                picture.convert('RGBA').save(output, format='PNG')
            name = f'grid/{appid}{SUFFIXES[kind]}.png'
            art_updates[name] = output.getvalue()
            if kind == 'icon':
                entry.set('icon', str(Path(config) / name))
        changes.append((game.name, appid))
    for index, entry in enumerate(root.value):
        entry.name = str(index)
    binary = vdf.dumps(tree)
    vdf.loads(binary)
    return binary, art_updates, changes, skipped


def apply(steam, profile, games, backup_dir, overwrite=False, force=False, launch=True, collections=(), progress=lambda _: None):
    config = config_path(steam, profile)
    tags = collection_tags(config, collections)
    include_favorites = FAVORITES_TAG in {tag.casefold() for tag in tags}
    with write_lock(config):
        was_running = bool(running())
        stopped = False
        try:
            shutdown(steam, force, progress)
            stopped = True
            original = snapshot_files(config, include_favorites)
            before = {k: hashlib.sha256(v).hexdigest() for k, v in original.items()}
            progress('Preparing shortcuts and artwork...')
            binary, images, changes, skipped = prepare(config, games, overwrite, tags)
            if not changes:
                return {'changed': [], 'skipped': skipped, 'backup': ''}
            progress('Creating backup...')
            saved = backup(config, backup_dir, include_localconfig=include_favorites)
            if running() or fingerprint(config, include_favorites) != before:
                raise SteamBusy('Steam restarted or the library changed. Try again.')
            updated = Snapshot(original, links=dict(original.links))
            updated['shortcuts.vdf'] = binary
            if include_favorites:
                updated['localconfig.vdf'] = update_favorites(config, [appid for _, appid in changes])
            for name, data in images.items():
                stem = Path(name).stem
                for old in list(updated):
                    if old.startswith('grid/') and Path(old).stem == stem and Path(old).suffix.casefold() in {'.png', '.jpg', '.jpeg', '.webp'}:
                        del updated[old]
                updated[name] = data
                updated.links.pop(name, None)
            for alias, target in list(updated.links.items()):
                if alias not in updated or target not in updated:
                    updated.links.pop(alias)
                else:
                    updated[alias] = updated[target]
            try:
                progress('Updating Steam...')
                replace_snapshot(config, updated)
                progress('Verifying Steam files...')
                if fingerprint(config, include_favorites) != {k: hashlib.sha256(v).hexdigest() for k, v in updated.items()}:
                    raise IOError('Write verification failed')
            except Exception:
                replace_snapshot(config, original)
                raise
            return {'changed': changes, 'skipped': skipped, 'backup': str(saved)}
        finally:
            # NSLM leaves Steam closed unless the caller explicitly asks to
            # launch it. This gives Big Picture users a deliberate choice.
            if stopped and launch:
                restart(steam)


def restore(steam, profile, archive, backup_dir, force=False, launch=True, progress=lambda _: None):
    config = config_path(steam, profile)
    desired = read_backup(archive, profile)
    with write_lock(config):
        was_running, stopped = bool(running()), False
        try:
            shutdown(steam, force, progress)
            stopped = True
            original = snapshot_files(config)
            saved = backup(config, backup_dir)
            if running():
                raise SteamBusy('Steam restarted. Restore cancelled.')
            try:
                replace_snapshot(config, desired)
                if fingerprint(config) != {k: hashlib.sha256(v).hexdigest() for k, v in desired.items()}:
                    raise IOError('Restore verification failed')
            except Exception:
                replace_snapshot(config, original)
                raise
            return str(saved)
        finally:
            if stopped and (was_running or launch):
                restart(steam)
