"""Bundle portable distribution, source archive, and dependency notices."""
from pathlib import Path
import importlib.metadata
import shutil
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
package = root / 'dist' / 'NSLM'
for name in ['README.md', 'THIRD-PARTY-NOTICES.md']:
    shutil.copy2(root / name, package / name)
licenses = package / 'licenses'
licenses.mkdir(exist_ok=True)
for name in ['PySide6', 'PySide6_Essentials', 'shiboken6', 'requests', 'urllib3', 'certifi', 'charset-normalizer', 'idna', 'pillow', 'pefile', 'psutil', 'pyinstaller']:
    distribution = importlib.metadata.distribution(name)
    for file in distribution.files or []:
        if any(token in str(file).lower() for token in ['license', 'copying', 'copyright']) and file.suffix.lower() not in {'.py', '.pyc', '.dll', '.pyd'}:
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = licenses / name / str(file).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
shutil.make_archive(str(root / 'dist' / 'NSLM-Windows-x64'), 'zip', root / 'dist', 'NSLM')
with zipfile.ZipFile(root / 'dist' / 'NSLM-Source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for directory in ['shelf', 'tests', 'tools', 'assets']:
        for file in (root / directory).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                archive.write(file, 'NSLM/' + file.relative_to(root).as_posix())
    for filename in [
        'main.py', 'NSLM.spec', 'NSLM-linux.spec',
        'requirements.txt', 'requirements-dev.txt',
        'build.ps1', 'build-linux.sh', 'install-steamdeck.sh',
        'README.md', 'THIRD-PARTY-NOTICES.md', 'LICENSE', 'pytest.ini',
    ]:
        archive.write(root / filename, 'NSLM/' + filename)
