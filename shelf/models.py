from dataclasses import dataclass, field, asdict
from pathlib import Path
import hashlib
import re
import unicodedata


def normal_path(value: str) -> str:
    return str(Path(value.strip('"')).resolve()).casefold()


def identity(exe: str, args: str = '') -> str:
    return hashlib.sha256((normal_path(exe) + '\0' + args.strip()).encode()).hexdigest()[:24]


def normalized_title(value: str) -> str:
    value = clean_name(value).casefold()
    value = re.sub(r'(?i)\b(?:launcher|game|win64|win32|shipping)\b', ' ', value)
    return re.sub(r'[^a-z0-9]+', '', value)


def clean_name(value: str) -> str:
    value = value.replace('™', '').replace('®', '').replace('©', '').replace('\ufffd', '')
    value = unicodedata.normalize('NFKC', value)
    value = ''.join(ch for ch in value if not unicodedata.category(ch).startswith('C'))
    value = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', value)
    value = re.sub(r'\[[^\]]*\]', '', value)
    value = re.sub(r'(?i)\(\s*\d+(?:\.\d+)?\s*(?:gb|mb)\s*\)', '', value)
    value = re.sub(r'(?i)\bbuild[ ._-]*\d+[a-z0-9._-]*\b', '', value)
    value = re.sub(r'(?i)\b(?:v\d+(?:\.\d+)*|win64|win32|shipping|x64|x86)\b', '', value)
    value = re.sub(r'[_.]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip(' .-_')


@dataclass
class Game:
    name: str
    exe: str
    args: str = ''
    source: str = ''
    kind: str = 'pc'
    confidence: int = 0
    reasons: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    search_names: list[str] = field(default_factory=list)
    appid: int = 0
    existing: bool = False
    selected: bool = True
    sgdb_id: int = 0
    art: dict[str, str] = field(default_factory=dict)
    # Original provider URLs let the editor mark the current image among the
    # official Steam and SteamGridDB gallery thumbnails after reopening.
    art_sources: dict[str, str] = field(default_factory=dict)
    note: str = ''
    start_dir: str = ''
    pending: bool = False

    @property
    def key(self):
        return identity(self.exe, self.args)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Source:
    path: str
    kind: str = 'pc'
    emulator: str = ''
    args_template: str = '-f -g "{rom}"'
    extensions: str = ''
    enabled: bool = True


def is_emulator(kind: str) -> bool:
    return kind in {'eden', 'switch_ryujinx', 'switch_yuzu', 'custom', 'switch'}


ART_TYPES = {'portrait': 'Cover', 'landscape': 'Grid', 'hero': 'Hero', 'logo': 'Logo', 'icon': 'Icon'}

EMULATOR_PRESETS = {
    'pc': {
        'label': 'Windows PC Games',
        'kind': 'pc',
        'emulator': '',
        'args_template': '',
        'extensions': '.exe',
    },
    'linux_pc': {
        'label': 'Linux PC Games',
        'kind': 'linux_pc',
        'emulator': '',
        'args_template': '',
        'extensions': '',
    },
    'switch_ryujinx': {
        'label': 'Nintendo Switch · Ryujinx (EmuDeck)',
        'kind': 'switch_ryujinx',
        'emulator': 'Ryujinx.exe',
        'args_template': '"{rom}"',
        'extensions': '.nsp, .xci',
    },
    'switch_yuzu': {
        'label': 'Nintendo Switch · Yuzu / Eden / Suyu',
        'kind': 'switch_yuzu',
        'emulator': 'yuzu.exe',
        'args_template': '-f -g "{rom}"',
        'extensions': '.nsp, .xci, .nro',
    },
    'custom': {
        'label': 'Custom Emulator / ROMs',
        'kind': 'custom',
        'emulator': '',
        'args_template': '"{rom}"',
        'extensions': '',
    },
}
