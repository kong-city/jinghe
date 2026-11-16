# -*- mode: python ; coding: utf-8 -*-
# 精核 · onefile / windowed 打包配置
# 构建：python build.py   （等价于 pyinstaller --noconfirm --clean build.spec）
# 产物：dist/Jinghe.exe
#
# 打包后 app.py 通过 sys._MEIPASS 定位 ui/ 与 vendor/；
# 提取任务用 exe 自我重入 `Jinghe.exe --cli ...`，不依赖外部 Python。

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('ui', 'ui'), ('vendor', 'vendor')],
    hiddenimports=['extract', 'format_registry', 'media_tools', 'media_runtime', 'word_input', 'word_export', 'audio_transcribe', 'video_transcribe', 'self_update'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Jinghe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
