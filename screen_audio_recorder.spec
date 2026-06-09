# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec ファイル: screen-audio-recorder
#
# ビルドコマンド:
#   pyinstaller screen_audio_recorder.spec
#
# 要件 1.1: 管理者権限なしで起動できる（uac_admin=False）
# 要件 1.3: ユーザーのホームディレクトリ配下にのみファイルを書き込む

import sys
from pathlib import Path
import importlib

block_cipher = None

# janome の辞書データ（sysdic）のパスを取得
_janome_datas = []
try:
    import janome.sysdic
    _janome_sysdic_dir = str(Path(janome.sysdic.__file__).parent)
    _janome_datas.append((_janome_sysdic_dir, "janome/sysdic"))
except ImportError:
    pass

# imageio-ffmpeg のバイナリディレクトリを取得
try:
    import imageio_ffmpeg
    _ffmpeg_binaries_dir = str(Path(imageio_ffmpeg.__file__).parent / "binaries")
    if Path(_ffmpeg_binaries_dir).exists():
        _janome_datas.append((_ffmpeg_binaries_dir, "imageio_ffmpeg/binaries"))
except ImportError:
    pass

# ffmpeg.exe のパスを検索（imageio-ffmpeg → プロジェクトルートの _internal/ → PATH）
_ffmpeg_src = None

# 1. imageio-ffmpeg パッケージのバイナリを探す
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    _ffmpeg_found = get_ffmpeg_exe()
    if _ffmpeg_found and Path(_ffmpeg_found).exists():
        _ffmpeg_src = Path(_ffmpeg_found)
except ImportError:
    pass

# 2. プロジェクトルートの _internal/ffmpeg.exe を探す
if _ffmpeg_src is None:
    _candidate = Path("_internal/ffmpeg.exe")
    if _candidate.exists():
        _ffmpeg_src = _candidate

# 3. PATH から ffmpeg.exe を探す
if _ffmpeg_src is None:
    import shutil
    _ffmpeg_found = shutil.which("ffmpeg")
    if _ffmpeg_found:
        _ffmpeg_src = Path(_ffmpeg_found)

# バイナリデータ（ffmpeg.exe を同梱）
_binaries = []
if _ffmpeg_src and _ffmpeg_src.exists():
    _binaries.append((str(_ffmpeg_src), "_internal"))

a = Analysis(
    ["src/screen_audio_recorder/main.py"],
    pathex=["src"],
    binaries=_binaries,
    datas=_janome_datas,
    hiddenimports=[
        # faster-whisper / CTranslate2 の動的インポート
        "ctranslate2",
        "faster_whisper",
        # janome の辞書データ
        "janome",
        "janome.tokenizer",
        # PyAudioWPatch
        "pyaudiowpatch",
        # tkinter
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        # filelock
        "filelock",
        # numpy
        "numpy",
        # imageio-ffmpeg（ffmpeg バイナリ同梱）
        "imageio_ffmpeg",
        # opencv（dxcam が内部で使用）
        "cv2",
        # mss（画面キャプチャ）
        "mss",
        # sounddevice（音声録音）
        "sounddevice",
        "_sounddevice_data",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不要なモジュールを除外してサイズを削減
        "matplotlib",
        "scipy",
        "pandas",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="screen-audio-recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # GUI アプリのためコンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 管理者権限を要求しない（要件 1.1）
    uac_admin=False,
    uac_uiaccess=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    # --onedir モード: dist/screen-audio-recorder/ に展開
    name="screen-audio-recorder",
)
