# NSLM

**NSLM — Non-Steam Game Library Manager** is a Windows desktop app for discovering games outside Steam, adding them as non-Steam shortcuts, and keeping their Steam library artwork tidy.

It is designed for Windows 10 and Windows 11 (x64), uses an English dark interface, and never modifies game files or saves.

## Download

Download the latest `NSLM-Windows-x64.zip` from the repository's [Releases](../../releases) page. Extract the entire archive, then run `NSLM.exe`. Keep the `_internal` folder next to the executable.

No Python installation is needed for the packaged app.

## What NSLM does

- Scans one or more game folders without blocking the interface.
- Finds sensible launch executables using folder names, Windows metadata, Unity and Unreal markers, and launcher heuristics.
- Detects installed native Steam games to avoid offering duplicates as non-Steam shortcuts.
- Supports standalone Windows games plus custom emulator and Nintendo Switch ROM entries.
- Reconciles an existing non-Steam library instead of blindly adding duplicates.
- Downloads Steam library artwork in five forms: Cover, Grid, Hero, Logo, and Icon.
- Uses official Steam artwork first, then falls back to SteamGridDB when Steam does not provide an image.
- Shows official Steam and SteamGridDB alternatives together in the artwork picker, with the official choices first.
- Lets you add shortcuts to Steam collections, including Favorites, or leave them Uncategorized.
- Creates an automatic, verified backup before every Steam-library write and can restore a backup later.
- Shows a live progress window while Steam is being updated, then leaves Steam closed until you explicitly choose **Launch Steam**.

## First run

1. Open **Settings → Steam**, confirm the Steam installation folder, and select your Steam profile.
2. Optionally open **Settings → Artwork** and enter a free [SteamGridDB API key](https://www.steamgriddb.com/profile/preferences/api). It supplies community alternatives and artwork for games that are not in the Steam store; official Steam artwork works without it.
3. Open **Folders** and add your PC game folders and, if needed, emulator ROM folders. Save the folder list.
4. Go back to **Library** and click **Rescan**.
5. Review new and low-confidence entries. Use **Edit** to adjust a launch command, match a SteamGridDB game, or choose a specific artwork variant.
6. Select the games to add and click **Add / Update**. NSLM shows a progress window while it safely updates Steam.
7. When the update is complete, choose **OK** to keep Steam closed or **Launch Steam** to open it.

## Artwork sources

NSLM reads the official artwork published by Steam directly. SteamDB is a helpful catalogue for inspecting that official data, but NSLM does not scrape SteamDB pages.

SteamGridDB is an optional community fallback. A SteamGridDB match is not treated as better than an official Steam match: if official Steam artwork becomes available, NSLM upgrades the previous community fallback automatically for newly scanned games. Manual artwork choices are preserved.

## Safety and local data

Before a Steam update, NSLM asks Steam to close, creates a ZIP backup, writes shortcut and artwork updates atomically, and verifies the result. It changes only the selected Steam profile's non-Steam shortcut configuration and grid artwork; it does not alter installed games, game folders, saves, or native Steam library metadata.

### Important

NSLM is an independent third-party utility. It is not affiliated with, endorsed by, sponsored by, or licensed by Valve Corporation, Steam, SteamDB, or SteamGridDB. Steam and the Steam logo are trademarks and/or registered trademarks of Valve Corporation in the U.S. and/or other countries.

NSLM does not include, download, distribute, unlock, or modify game executables, game content, DRM, Steam accounts, or Steam purchases. Artwork is requested from the selected public artwork source and cached only on the user's own computer.

Backups and verification are intended to reduce the risk of an accidental library change, not eliminate it. Always review the selected profile and changes before updating Steam, and keep the generated backup until you have confirmed that your library looks correct. You use NSLM at your own risk; the software is provided without warranty, as set out in the [MIT License](LICENSE).

Application data is stored under `%LOCALAPPDATA%\NSLM\`:

- `settings.json` — Steam path, selected profile, and scan folders.
- `catalog.json` — Saved launch choices, matches, and artwork references.
- `images\` — NSLM's local artwork cache.
- `backups\` — Verified backups of non-Steam shortcuts and artwork.
- `error.log` — Unexpected-error log, if needed.

SteamGridDB API keys are stored with Windows DPAPI rather than as plain text.

## Build from source

Requirements: Python 3.12+ on Windows and a Steam installation for full end-to-end testing.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
python main.py
```

To build the distributable Windows archive:

```powershell
.\build.ps1
```

The generated archive is written to `dist\NSLM-Windows-x64.zip`.

## Third-party notices

Bundled third-party license notices are included in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) and in the packaged application.

## Contributing and support

Bug reports and feature requests are welcome in [GitHub Issues](../../issues). Please include the NSLM version, Windows version, steps to reproduce the issue, and the relevant part of `error.log` with any personal paths or API keys removed.

NSLM is a free open-source project. If it saves you time, you can [support its development on Ko-fi](https://ko-fi.com/dgorbatko). Donations are voluntary and help fund development and testing; they do not provide a commercial support contract.
