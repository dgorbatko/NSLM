# Native tools (pip, pytest and PyInstaller) may emit ordinary diagnostics on
# stderr.  Under Windows OpenSSH, treating every stderr line as a terminating
# PowerShell error aborts an otherwise successful build.  Every native step
# below already checks $LASTEXITCODE explicitly.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot -ErrorAction Stop
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create build environment' }
}
& '.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& '.venv\Scripts\python.exe' tools\make_icon.py
$pytestTemp = Join-Path -Path $PSScriptRoot -ChildPath ('artifacts\pytest-' + [guid]::NewGuid().ToString('N'))
& '.venv\Scripts\python.exe' -m pytest -q tests -p no:cacheprovider --basetemp $pytestTemp
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& '.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean NSLM.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
& '.venv\Scripts\python.exe' tools\smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Packaged application smoke test failed' }
& '.venv\Scripts\python.exe' tools\package.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
