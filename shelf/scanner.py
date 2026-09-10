from pathlib import Path
import os
import re
import json
from difflib import SequenceMatcher
import ctypes
import time
from functools import lru_cache
from .models import Game, Source, clean_name, normal_path, is_emulator

SKIP_DIRS = {
    'windows', '$recycle.bin', 'system volume information', 'node_modules', '.git',
    '__installer', '_commonredist', 'redist', 'directx', 'dotnet', 'support',
    'crashreporter', 'easyanticheat', 'battleye', 'engine', 'steamapps',
    'steamdeck-migration', 'emulation', 'crack', 'cracks', 'nodvd',
}
BAD_EXE = re.compile(r'(?i)(unins|uninstall|setup|install(er)?$|bootstrap(?:packaged)?game|bootstrapper|crash|reporter|vcredist|dxsetup|dxwebsetup|dotnet|unitycrash|ue4prereq|ueprereq|cef|webhelper|notification|updat(er|e)$|config(urator)?$|server$|benchmark$|redistribut|diagnostic|testapp$|debug$)')
GENERIC = {'game', 'launcher', 'start', 'play', 'launch', 'bootstrap', 'shipping'}
GENERIC_TITLES = {
    'game', 'launcher', 'start', 'play', 'launch', 'bootstrap', 'shipping',
    'bootstrappackagedgame', 'unrealengine', 'unity', 'ue4', 'ue5',
    'microsoftwindowsoperatingsystem',
}


@lru_cache(maxsize=4096)
def _version_info(filename, size, modified):
    """Read Windows version resources without parsing entire executable files."""
    try:
        api = ctypes.windll.version
        length = api.GetFileVersionInfoSizeW(ctypes.c_wchar_p(filename), None)
        if not length or length > 8 * 1024 * 1024:
            return {}
        buffer = ctypes.create_string_buffer(length)
        if not api.GetFileVersionInfoW(ctypes.c_wchar_p(filename), 0, length, buffer):
            return {}
        pointer, count = ctypes.c_void_p(), ctypes.c_uint()
        translations = [(0x0409, 0x04b0), (0x0409, 0x04e4)]
        if api.VerQueryValueW(buffer, ctypes.c_wchar_p('\\VarFileInfo\\Translation'), ctypes.byref(pointer), ctypes.byref(count)):
            words = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort))
            translations = [(words[i], words[i+1]) for i in range(0, count.value // 2 - 1, 2)] + translations
        result = {}
        for lang, codepage in translations:
            for field in ('ProductName', 'FileDescription', 'InternalName', 'OriginalFilename'):
                if field in result:
                    continue
                key = f'\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}'
                if api.VerQueryValueW(buffer, ctypes.c_wchar_p(key), ctypes.byref(pointer), ctypes.byref(count)) and count.value:
                    value = ctypes.wstring_at(pointer, count.value).rstrip('\0').strip()
                    if value:
                        result[field] = value
        return result
    except (OSError, AttributeError):
        pass
    return {}


def product_info(path):
    try:
        stat = path.stat()
        return _version_info(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return {}


def useful_title(value):
    title = clean_name(value or '')
    key = re.sub(r'[\W_]+', '', title.casefold())
    return title if len(key) >= 3 and key not in GENERIC_TITLES else ''


def gog_metadata(root):
    names, fallbacks, primary_paths = [], [], set()
    for manifest in list(root.glob('goggame-*.info'))[:8]:
        try:
            data = json.loads(manifest.read_text('utf-8-sig'))
            tasks = data.get('playTasks', []) or []
            # DLC manifests commonly sit beside the base game but have no playable task.
            # Use them only as a last-resort search hint, never as the displayed title.
            (names if tasks else fallbacks).append(data.get('name'))
            for task in tasks:
                if task.get('isPrimary') or task.get('category') == 'game':
                    names.append(task.get('name'))
                if task.get('isPrimary') and task.get('path'):
                    primary_paths.add(str(task['path']).replace('\\', '/').casefold())
        except (OSError, ValueError, TypeError):
            continue
    return names + fallbacks, primary_paths


def title_candidates(path, root, metadata=None):
    """Collect trustworthy local title hints, strongest first."""
    metadata = metadata or {}
    result = []

    def add(value):
        title = useful_title(value)
        if title and all(title.casefold() != old.casefold() for old in result):
            result.append(title)

    # GOG ships an authoritative title next to the primary launcher.
    gog_names, _ = gog_metadata(root)
    for name in gog_names:
        add(name)

    internal_dirs = {'bin', 'binaries', 'content', 'engine', 'game', 'win64', 'win32', 'x64', 'x86'}
    structural = []
    try:
        for part in path.parent.relative_to(root).parts:
            if part.casefold() not in internal_dirs:
                structural.append(part)
    except ValueError:
        pass
    structural.extend((root.name, path.stem))
    cleaned_structural = [clean_name(value) for value in structural]
    for index, value in enumerate(cleaned_structural):
        reduced = re.sub(r'(?i)^(?:run|launch|play|start)\s+', '', value)
        if reduced != value and any(
                re.sub(r'[\W_]+', '', other.casefold()) == re.sub(r'[\W_]+', '', reduced.casefold())
                for other_index, other in enumerate(cleaned_structural) if other_index != index):
            cleaned_structural[index] = reduced
    # A descriptive install-folder or launcher name is usually safer than a short
    # engine/product field such as "Split", "Session Game", or "UE4".
    for value in sorted(cleaned_structural, key=lambda item: (-len(item.split()), -len(item))):
        add(value)
    for field in ('ProductName', 'FileDescription', 'InternalName'):
        add(metadata.get(field, ''))
    original = Path(metadata.get('OriginalFilename', '')).stem
    add(original)
    for shortcut in list(root.glob('*.lnk'))[:12]:
        add(re.sub(r'(?i)^(?:launch|play|start)\s+', '', shortcut.stem))
    return result


def rank_exe(path, root):
    if BAD_EXE.search(path.stem):
        return None
    score, reasons = 30, []
    metadata = product_info(path)
    names = title_candidates(path, root, metadata)
    product = useful_title(metadata.get('ProductName', ''))
    if product:
        score += 18
        reasons.append('Name from executable properties')
    gog_names, gog_primary = gog_metadata(root)
    if gog_names:
        reasons.append('Name from GOG metadata')
    try:
        relative_exe = path.relative_to(root).as_posix().casefold()
    except ValueError:
        relative_exe = ''
    if relative_exe in gog_primary:
        score += 48
        reasons.append('Primary executable from GOG metadata')
    folder_name = clean_name(root.name)
    stem = clean_name(path.stem)
    match = SequenceMatcher(None, re.sub(r'\W', '', stem.casefold()), re.sub(r'\W', '', folder_name.casefold())).ratio()
    if match > .65:
        score += 22
        reasons.append('Executable matches the folder name')
    if path.with_name(path.stem + '_Data').is_dir():
        score += 28
        reasons.append('Unity game data found')
    if 'shipping' in path.stem.casefold():
        score += 24
        reasons.append('Unreal Engine game executable')
    if (path.parent / 'steam_api64.dll').exists() or (path.parent / 'steam_api.dll').exists():
        score += 12
        reasons.append('Steam API library found beside executable')
    if path.parent == root:
        score += 12
    if path.stem.casefold() in GENERIC:
        score -= 12
    # Prefer the packaged root bootstrapper; it can set prerequisites and working directory.
    if (root / 'Engine').exists() and path.parent == root:
        score += 18
        reasons.append('Unreal Engine launcher')
    title = names[0] if names else (folder_name or stem)
    if title.casefold() == folder_name.casefold() and not any('folder name' in reason.casefold() for reason in reasons):
        reasons.append('Name from game folder')
    return min(99, score), title, reasons, names


def walk_files(root, cancel, warnings, progress=lambda _: None, suffixes=None):
    last_report, count = 0, 0
    def onerror(err):
        warnings.append(f'Access denied: {err.filename}')
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        if cancel.is_set():
            raise InterruptedError('Scan cancelled')
        dirs[:] = [d for d in dirs if d.casefold() not in SKIP_DIRS and not (Path(directory) / d).is_symlink() and not (Path(directory) / d).is_junction()]
        if len(Path(directory).relative_to(root).parts) >= 10:
            dirs[:] = []
        count += len(files)
        if time.monotonic() - last_report > .15:
            progress(f'Scanning {root.name}: {count:,} files checked · {Path(directory).name}')
            last_report = time.monotonic()
        for filename in files:
            if cancel.is_set():
                raise InterruptedError('Scan cancelled')
            if suffixes is None or os.path.splitext(filename)[1].casefold() in suffixes:
                yield Path(directory) / filename


def scan(sources, cancel, progress=lambda _: None):
    found, warnings = {}, []
    for source_data in sources:
        source = Source(**source_data) if isinstance(source_data, dict) else source_data
        if not source.enabled:
            continue
        root = Path(source.path)
        if not root.is_dir():
            warnings.append(f'Folder unavailable: {root}')
            continue
        progress(f'Scanning: {root.name}')
        is_emu = is_emulator(source.kind)
        if is_emu:
            if source.extensions:
                raw_exts = [e.strip().casefold() for e in source.extensions.split(',') if e.strip()]
                suffixes = {e if e.startswith('.') else f'.{e}' for e in raw_exts}
            elif source.kind in {'eden', 'switch_ryujinx', 'switch_yuzu'}:
                suffixes = {'.nsp', '.xci', '.nro'}
            else:
                suffixes = {'.nsp', '.xci', '.nro', '.iso', '.chd', '.rvz', '.zip'}
        else:
            suffixes = {'.exe'}

        files = list(walk_files(root, cancel, warnings, progress, suffixes))

        if is_emu:
            if not Path(source.emulator).is_file():
                warnings.append(f'Select emulator executable for {root.name}: {source.emulator or "Not configured"}')
                continue
            if '{rom}' not in source.args_template:
                warnings.append(f'Missing {{rom}} in emulator arguments for {root.name}')
                continue
            for path in files:
                if cancel.is_set():
                    raise InterruptedError('Scan cancelled')
                if path.suffix.casefold() not in suffixes:
                    continue
                # For Switch ROMs: filter updates and DLC
                if source.kind in {'eden', 'switch_ryujinx', 'switch_yuzu'}:
                    if re.search(r'(?i)(\bupdate\b|\bdlc\b|\bpatch\b)', path.stem):
                        continue
                    title_id = re.search(r'(?i)\b(010[0-9a-f]{13})\b', path.stem)
                    if title_id and not title_id[1].endswith('000'):
                        continue
                title = clean_name(path.stem)
                emu_desc = 'Ryujinx' if 'ryujinx' in source.kind else ('Yuzu' if 'yuzu' in source.kind else ('Eden' if source.kind == 'eden' else 'Emulator'))
                game = Game(
                    name=title,
                    exe=source.emulator,
                    args=source.args_template.replace('{rom}', str(path)),
                    source=str(path),
                    kind=source.kind,
                    confidence=85,
                    reasons=[f'{emu_desc} Switch ROM ({path.suffix})' if 'switch' in source.kind or source.kind == 'eden' else f'ROM ({path.suffix})']
                )
                found[game.key] = game
            continue

        groups = {}
        # Distinguish a collection folder from a single game folder
        root_exes = [p for p in files if p.parent == root and p.suffix.casefold() == '.exe' and not BAD_EXE.search(p.stem)]
        child_dirs_with_exes = {
            p.relative_to(root).parts[0]
            for p in files
            if len(p.relative_to(root).parts) > 1 and p.suffix.casefold() == '.exe' and not BAD_EXE.search(p.stem)
        }
        internal_dirs = {'bin', 'binaries', 'content', 'engine', 'game', 'win64', 'win32', 'x64', 'x86'}
        has_multiple_game_subdirs = len(child_dirs_with_exes - internal_dirs) > 1

        root_is_game = not has_multiple_game_subdirs and (
            (bool(root_exes) and (len(child_dirs_with_exes) == 0 or (root / 'Engine').exists())) or
            (root / 'Content').exists() or
            (root / 'Binaries').exists() or
            any(p.name.endswith('_Data') for p in root.iterdir() if p.is_dir())
        )

        last_report = 0
        for index, path in enumerate(files):
            if cancel.is_set():
                raise InterruptedError('Scan cancelled')
            if time.monotonic() - last_report > .15:
                progress(f'Checking executables: {index + 1}/{len(files)} · {path.name}')
                last_report = time.monotonic()
            if path.suffix.casefold() != '.exe':
                continue
            relative = path.relative_to(root)
            group_root = root if root_is_game or len(relative.parts) == 1 else root / relative.parts[0]
            ranked = rank_exe(path, group_root)
            if ranked:
                groups.setdefault(str(group_root), []).append((ranked[0], path, ranked[1], ranked[2], ranked[3]))
        for folder, candidates in groups.items():
            candidates.sort(key=lambda item: (-item[0], len(str(item[1])), str(item[1]).casefold()))
            score, path, title, reasons, search_names = candidates[0]
            ambiguous = len(candidates) > 1 and score - candidates[1][0] < 12
            if ambiguous:
                reasons.append('Multiple launch candidates; review the selection')
                score = min(score, 59)
            game = Game(title, str(path), source=folder, confidence=score, reasons=reasons or ['Candidate based on folder structure'], alternatives=[str(c[1]) for c in candidates], search_names=search_names, selected=score >= 60)
            found[game.key] = game
    return list(found.values()), warnings
