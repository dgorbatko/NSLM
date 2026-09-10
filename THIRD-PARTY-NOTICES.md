# Third-party components

NSLM (Non Steam Library Manager) is an independent application, not affiliated with Valve, SteamGridDB, or Eden. Game images remain the property of their respective rights holders and contributors. API access is subject to each provider's terms.

The packaged application dynamically loads these components. Original license text and notices are included under `_internal` by the build, supplemented in `licenses`:

- Python 3.12 — Python Software Foundation License.
- PySide6 / Shiboken6 and Qt — LGPL v3 / GPL v3 / commercial options. This build uses the LGPL distribution and dynamic libraries. See https://doc.qt.io/qtforpython-6/licenses.html and https://www.qt.io/licensing/open-source-lgpl-obligations . Corresponding source: https://download.qt.io/official_releases/QtForPython/ and https://download.qt.io/official_releases/qt/ . Users may replace the dynamically linked Qt libraries with compatible versions and reverse engineer for debugging modifications to these libraries.
- Requests — Apache License 2.0, https://github.com/psf/requests .
- urllib3 — MIT License, https://github.com/urllib3/urllib3 .
- certifi — Mozilla Public License 2.0, https://github.com/certifi/python-certifi .
- charset-normalizer — MIT License, https://github.com/jawah/charset_normalizer .
- idna — BSD License, https://github.com/kjd/idna .
- Pillow — MIT-CMU License, https://github.com/python-pillow/Pillow .
- pefile — MIT License, https://github.com/erocarrera/pefile .
- psutil — BSD 3-Clause License, https://github.com/giampaolo/psutil .
- PyInstaller bootloader — GPL v2 or later with distribution exception, https://pyinstaller.org/en/stable/license.html .

NSLM application source is included in the adjacent project folder. No Steam ROM Manager code is incorporated.
