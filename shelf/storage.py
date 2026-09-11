import base64
import ctypes
import json
import os
from pathlib import Path
import tempfile


def data_dir():
    override = os.environ.get('NSLM_DATA') or os.environ.get('STEAMSHELF_DATA')
    if override:
        path = Path(override)
    elif os.name == 'nt':
        path = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'NSLM'
    else:
        # SteamOS follows the normal Linux XDG layout.  Keeping NSLM's cache
        # here also avoids leaving application files directly in the home dir.
        path = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'NSLM'
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.nslm-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(value: str, decrypt=False) -> str:
    if not value:
        return ''
    if not hasattr(ctypes, 'windll'):
        if decrypt:
            raw = base64.b64decode(value)
            return bytes(b ^ 0x5a for b in raw).decode('utf-8')
        raw = bytes(b ^ 0x5a for b in value.encode('utf-8'))
        return base64.b64encode(raw).decode('ascii')
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    incoming = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError('Windows could not decrypt the saved key. Enter it again.')
    try:
        result = ctypes.string_at(outgoing.data, outgoing.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.data)


class Store:
    def __init__(self, root=None):
        self.root = Path(root or data_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = self.read('settings.json', {
            'sources': [], 'steam': '', 'profile': '', 'auto_scan': False,
            'restart': True, 'remote_play_enabled': False, 'remote_shortcuts': '',
        })
        self.catalog = self.read('catalog.json', {})
        migrated = False
        # Purge credentials and catalog-only metadata from the retired integration.
        for key in ('igdb_client', 'igdb_secret'):
            migrated = self.settings.pop(key, None) is not None or migrated
        for item in self.catalog.values():
            if not isinstance(item, dict):
                continue
            for key in ('summary', 'year', 'genres'):
                migrated = item.pop(key, None) is not None or migrated
        if migrated:
            self.save()

    def read(self, name, default):
        path = self.root / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text('utf-8'))
        except (ValueError, OSError) as error:
            raise RuntimeError(f'Could not read {path}. File was not changed: {error}') from error

    def save(self):
        atomic_write(self.root / 'settings.json', json.dumps(self.settings, ensure_ascii=False, indent=2).encode())
        atomic_write(self.root / 'catalog.json', json.dumps(self.catalog, ensure_ascii=False, indent=2).encode())

    def secret(self, name):
        return protect(self.settings.get(name, ''), decrypt=True)

    def set_secret(self, name, value):
        self.settings[name] = protect(value)
