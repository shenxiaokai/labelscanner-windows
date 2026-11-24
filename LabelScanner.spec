# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件 .exe，无控制台窗口。"""

from PyInstaller.utils.hooks import collect_all

onnx_datas, onnx_binaries, onnx_hidden = collect_all("onnxruntime")
rapid_datas, rapid_binaries, rapid_hidden = collect_all("rapidocr_onnxruntime")

a = Analysis(
    ["labelscanner.py"],
    pathex=[],
    binaries=onnx_binaries + rapid_binaries,
    datas=[("models", "models")] + onnx_datas + rapid_datas,
    hiddenimports=["rapidocr_onnxruntime", "onnxruntime", "zxingcpp",
                   "cv2", "PIL", "numpy"] + onnx_hidden + rapid_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LabelScanner",
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
    icon=None,
)
