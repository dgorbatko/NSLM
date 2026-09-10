"""Launch the packaged EXE against a temporary Steam/game fixture. Never uses real Steam."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import shutil

root = Path(__file__).resolve().parents[1]
output = root / 'artifacts' / 'packaged-smoke'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='nslm-smoke-') as temporary:
    fixture = Path(temporary)
    steam = fixture / 'Steam'
    (steam / 'userdata' / '123' / 'config').mkdir(parents=True)
    (steam / 'steam.exe').write_bytes(b'fixture-do-not-execute')
    games = fixture / 'Games'
    (games / 'Example' / 'Example_Data').mkdir(parents=True)
    (games / 'Example' / 'Example.exe').write_bytes(b'fixture-do-not-execute')
    data = fixture / 'data'
    data.mkdir()
    (data / 'settings.json').write_text(json.dumps({'steam': str(steam), 'profile': '123', 'auto_scan': False,
        'sources': [{'path': str(games), 'kind': 'pc', 'emulator': '', 'args_template': '-f -g "{rom}"', 'enabled': True}]}), 'utf-8')
    env = dict(os.environ, NSLM_DATA=str(data), NSLM_SMOKE_DIRECTORY=str(output), QT_QPA_PLATFORM='offscreen')
    binary_name = 'NSLM.exe' if os.name == 'nt' else 'NSLM'
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    result = subprocess.run([str(root / 'dist' / 'NSLM' / binary_name)], env=env, timeout=30,
                            creationflags=flags, capture_output=True, text=True)
    (output / 'process.txt').write_text(f'Exit: {result.returncode}\n{result.stdout}\n{result.stderr}', 'utf-8')
    if result.returncode != 0:
        shutil.copytree(data, output / 'failed-data', dirs_exist_ok=True)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert not (data / 'error.log').exists(), (data / 'error.log').read_text('utf-8')
    report = json.loads((output / 'smoke.json').read_text('utf-8'))
    assert report['visible'] and report['pages'] == 3
    catalog = json.loads((data / 'catalog.json').read_text('utf-8'))
    assert len(catalog) == 1 and next(iter(catalog.values()))['name'] == 'Example'
    assert not (steam / 'userdata' / '123' / 'config' / 'shortcuts.vdf').exists()
    report['scan_game'] = 'Example'
    report['steam_files_unchanged'] = True
    (output / 'smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print('Packaged EXE: launch, three pages, scan, catalog persistence and clean exit passed. Steam files unchanged.')
