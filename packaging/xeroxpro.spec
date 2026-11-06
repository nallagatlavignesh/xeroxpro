# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller packaging/xeroxpro.spec --noconfirm        (run from the project root, on the target OS)
# Output: dist/XeroxPro/  (one folder; "onedir" starts faster and is flagged by antivirus less often than "onefile")
# User data is NEVER stored here: it lives in %LOCALAPPDATA%\XeroxPro, so updating or reinstalling keeps all records.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "resources" / "icons" / "xeroxpro.ico") if sys.platform == "win32" else None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "resources"), "resources"),  # fonts, translations, styles, icons
        (str(ROOT / "database" / "migrations" / "*.sql"), "database/migrations"),  # schema scripts are data, not code
    ],
    hiddenimports=["sqlalchemy.dialects.sqlite", "selftest"],
    excludes=[  # modules we never use; keeps the download small
        "tkinter", "matplotlib", "numpy", "PIL", "pytest", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtMultimedia", "PySide6.QtBluetooth",
        "PySide6.QtSql", "PySide6.QtNetwork", "PySide6.QtDesigner", "PySide6.QtTest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="XeroxPro",
    console=False,  # no black console window; use `XeroxPro.exe --selftest report.txt` for diagnostics
    icon=ICON,
    upx=False,  # UPX-packed exes trigger more antivirus warnings
)
coll = COLLECT(exe, a.binaries, a.datas, name="XeroxPro", upx=False)
