#!/usr/bin/env bash
set -euo pipefail

# Run this script on Linux x86_64 (the Steam Deck is the reference target).
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install --upgrade pip
.venv-linux/bin/python -m pip install -r requirements-dev.txt
mkdir -p artifacts
.venv-linux/bin/python -m pytest -q tests -p no:cacheprovider --basetemp "artifacts/pytest-linux"
.venv-linux/bin/python -m PyInstaller --noconfirm --clean NSLM-linux.spec
.venv-linux/bin/python tools/smoke.py
cp README.md THIRD-PARTY-NOTICES.md LICENSE dist/NSLM/

mkdir -p dist
rm -f dist/NSLM-SteamDeck-Linux-x64.zip
(
  cd dist
  zip -qry "NSLM-SteamDeck-Linux-x64.zip" NSLM
)
sha256sum dist/NSLM-SteamDeck-Linux-x64.zip > dist/NSLM-SteamDeck-Linux-x64.zip.sha256
