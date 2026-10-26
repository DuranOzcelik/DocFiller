# PyInstaller build description.
#
#     pyinstaller docfiller.spec --noconfirm
#
# Produces a single self-contained dist/DocFiller.exe. No templates or data are
# bundled: the program works on whatever folder the user points it at.
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

analysis = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Office automation; imported lazily so the static analyser misses them.
        "win32com.client",
        "pythoncom",
        "pywintypes",
        # The PDF preview is imported inside a try block for the same reason.
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        # Legacy .xls support is only reached at run time.
        "xlrd",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here is used; excluding them keeps the executable substantially
    # smaller and the build faster.
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="DocFiller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # A desktop program must not flash a console window on start.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
