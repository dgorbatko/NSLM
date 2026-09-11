#!/usr/bin/env bash
# Install or update NSLM on Steam Deck / Linux x86_64 without Python.
set -euo pipefail

repo="dgorbatko/NSLM"
asset="NSLM-SteamDeck-Linux-x64.zip"
release_url="https://github.com/${repo}/releases/latest/download/${asset}"
checksum_url="${release_url}.sha256"
install_dir="${NSLM_INSTALL_DIR:-$HOME/Applications/NSLM}"
desktop_file="${NSLM_DESKTOP_FILE:-$HOME/.local/share/applications/NSLM.desktop}"

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    echo "NSLM currently provides a Linux build for x86_64 only." >&2
    exit 1
    ;;
esac

for command in unzip sha256sum; do
  command -v "$command" >/dev/null || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done

download() {
  if command -v curl >/dev/null; then
    curl --fail --location --retry 3 --connect-timeout 20 --output "$2" "$1"
  elif command -v wget >/dev/null; then
    wget --tries=3 --timeout=20 --output-document="$2" "$1"
  else
    echo "Install curl or wget, then run this installer again." >&2
    exit 1
  fi
}

tmp="$(mktemp -d "${TMPDIR:-/tmp}/nslm-install.XXXXXX")"
stage=""
cleanup() {
  rm -rf "$tmp"
  if [[ -n "$stage" && -d "$stage" ]]; then
    rm -rf "$stage"
  fi
}
trap cleanup EXIT

archive="$tmp/$asset"
checksum="$tmp/$asset.sha256"
echo "Downloading NSLM for Steam Deck…"
download "$release_url" "$archive"
download "$checksum_url" "$checksum"

expected="$(awk 'NR == 1 { print $1 }' "$checksum")"
if [[ ! "$expected" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "The published SHA-256 file is invalid. Nothing was installed." >&2
  exit 1
fi
actual="$(sha256sum "$archive" | awk '{ print $1 }')"
if [[ "${actual,,}" != "${expected,,}" ]]; then
  echo "SHA-256 verification failed. Nothing was installed." >&2
  exit 1
fi
unzip -tq "$archive" >/dev/null

install_parent="$(dirname "$install_dir")"
mkdir -p "$install_parent"
stage="$(mktemp -d "$install_parent/.nslm-stage.XXXXXX")"
unzip -q "$archive" -d "$stage"
test -x "$stage/NSLM/NSLM" || {
  echo "The downloaded archive has an unexpected layout. Nothing was installed." >&2
  exit 1
}

if [[ -e "$install_dir" || -L "$install_dir" ]]; then
  backup="${install_dir}.previous-$(date +%Y%m%d-%H%M%S)"
  mv "$install_dir" "$backup"
  echo "Previous installation kept at: $backup"
fi
mv "$stage/NSLM" "$install_dir"
rmdir "$stage"
stage=""

mkdir -p "$(dirname "$desktop_file")"
desktop_tmp="${desktop_file}.tmp.$$"
printf '%s\n' \
  '[Desktop Entry]' \
  'Type=Application' \
  'Name=NSLM' \
  'Comment=Non-Steam Game Library Manager' \
  "Exec=$install_dir/NSLM" \
  "Icon=$install_dir/assets/logo-white.png" \
  'Terminal=false' \
  'Categories=Utility;Game;' > "$desktop_tmp"
chmod +x "$desktop_tmp"
mv "$desktop_tmp" "$desktop_file"
if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$(dirname "$desktop_file")" >/dev/null 2>&1 || true
fi

echo
echo "NSLM is installed at: $install_dir"
echo "Open it from the Desktop Mode application menu, or run: $install_dir/NSLM"
