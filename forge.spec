# -*- mode: python ; coding: utf-8 -*-
# Standalone Forge build. Ships the compiled TUI so the internals aren't
# distributed as plaintext source; the encrypted profile (templates.dat) rides
# inside and is still only unlocked at runtime with the FORGE_PROFILE key.
# Behaviour is unchanged — this is packaging only.
from PyInstaller.utils.hooks import collect_all

datas = [('assets/templates.dat', 'assets')]
binaries = []
hiddenimports = ['forge_core']

# textual (UI), truststore (OS cert store for TLS), cryptography (profile
# decrypt) need their data/binaries collected so the frozen build is complete.
for _pkg in ('textual', 'truststore', 'cryptography'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h
# openai + its httpx stack are pulled in by PyInstaller's bundled hooks.

a = Analysis(
    ['forge_tui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Forge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
